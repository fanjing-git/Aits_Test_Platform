"""REST endpoints for requirement ingestion, analysis and linkages."""

from pathlib import Path

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.configs.models import ModelConfig, ModelRoutingPolicy
from apps.configs.routing import ModelRouteError, ModelRouteResolver, required_model_types
from apps.configs.serializers import SafeModelSummarySerializer
from apps.projects.permissions import is_platform_admin
from apps.requirement_analysis.analyzer import RequirementAnalysisError, analyze_requirement_document
from apps.requirement_analysis.linkages import LinkageAnalysisError, identify_document_linkages
from apps.requirement_analysis.limits import requirement_document_limit_label, requirement_document_max_bytes
from apps.requirement_analysis.llm_adapter import ModelAnalysisError, RequirementModelAdapter
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument
from apps.requirement_analysis.parser import DocumentParseError, parse_file, parse_requirement_document
from apps.requirement_analysis.permissions import RequirementPermission, can_manage_requirements
from apps.requirement_analysis.serializers import RequirementAnalysisConfirmationSerializer, RequirementAnalysisSerializer, RequirementDocumentSerializer
from apps.requirement_analysis.screenshot_analyzer import analyze_screenshot_file
from apps.requirement_analysis.services import RequirementAnalysisConfirmationError, RequirementAnalysisRecordService
from apps.skills.orchestration import SkillExecutionService


class RequirementDocumentViewSet(viewsets.ModelViewSet):
    """Manage project requirement sources and trigger the analysis pipeline."""

    serializer_class = RequirementDocumentSerializer
    permission_classes = (RequirementPermission,)
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def get_queryset(self):
        """Return only documents visible in the caller's project scope."""
        queryset = RequirementDocument.objects.select_related("project", "created_by").prefetch_related("analyses")
        if not is_platform_admin(self.request.user):
            queryset = queryset.filter(project__memberships__user=self.request.user) | queryset.filter(project__created_by=self.request.user)
        project = self.request.query_params.get("project")
        if project:
            queryset = queryset.filter(project_id=project)
        return queryset.distinct()

    def perform_create(self, serializer):
        """Require manager-level project access before creating a document."""
        project = serializer.validated_data["project"]
        if not can_manage_requirements(self.request.user, project):
            raise PermissionDenied("仅项目所有者、项目管理员或平台管理员可创建需求文档。")
        serializer.save()

    def perform_update(self, serializer):
        """Require manager-level project access before changing metadata."""
        document = self.get_object()
        if not can_manage_requirements(self.request.user, document.project):
            raise PermissionDenied("当前项目角色不能修改需求文档。")
        serializer.save()

    def perform_destroy(self, instance):
        """Allow only project managers to remove a requirement source."""
        if not can_manage_requirements(self.request.user, instance.project):
            raise PermissionDenied("当前项目角色不能删除需求文档。")
        instance.delete()

    def _require_manager(self, document):
        """Raise a permission error for analysis-mutating actions."""
        if not can_manage_requirements(self.request.user, document.project):
            raise PermissionDenied("当前项目角色不能执行需求分析操作。")

    @action(detail=True, methods=("post",), url_path="confirm-analysis")
    def confirm_analysis(self, request, pk=None):
        """Allow a project manager to confirm a reviewable analysis for generation."""
        document = self.get_object()
        self._require_manager(document)
        confirmation = RequirementAnalysisConfirmationSerializer(data=request.data)
        confirmation.is_valid(raise_exception=True)
        try:
            document = RequirementAnalysisRecordService().confirm_analysis(
                document,
                request.user,
                **confirmation.validated_data,
            )
        except RequirementAnalysisConfirmationError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        document.refresh_from_db()
        return Response(self.get_serializer(document).data)

    def _analysis_failure_response(self, document, exc: RequirementAnalysisError) -> Response:
        """Return a structured, safe analysis failure for the workbench."""
        document.refresh_from_db()
        latest = document.analyses.order_by("-created_at").first()
        partial = bool(latest and (latest.coverage_report or {}).get("analysis_method") == "model_partial")
        payload = {
            "detail": str(exc),
            "code": getattr(exc, "code", "analysis_error"),
            "status": "partial" if partial else "failed",
            "retryable": bool(getattr(exc, "retryable", False)),
            "document_status": document.status,
            "latest_analysis": RequirementAnalysisSerializer(latest).data if latest else None,
        }
        response_status = status.HTTP_502_BAD_GATEWAY if getattr(exc, "code", "") not in {
            "analysis_error", "model_capability_mismatch", "model_inactive", "model_not_found", "model_route_unavailable",
        } else status.HTTP_400_BAD_REQUEST
        return Response(payload, status=response_status)

    @staticmethod
    def _preferred_model_name(request, feature_key: str) -> str | None:
        """Validate an optional per-run model selection against feature capability."""
        raw_id = request.data.get("model_config_id")
        if raw_id in (None, "", "null"):
            return None
        try:
            config_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"model_config_id": "模型配置编号无效。"}) from exc
        config = ModelConfig.objects.filter(pk=config_id, is_active=True).first()
        if config is None:
            raise ValidationError({"model_config_id": "模型不存在或已停用，请重新选择。"})
        if config.model_type not in set(required_model_types(feature_key)):
            raise ValidationError({"model_config_id": "所选模型不支持该功能所需能力。"})
        return config.name

    @action(detail=True, methods=("get",), url_path="model-options")
    def model_options(self, request, pk=None):
        """Return selectable models and the effective route for one document."""
        document = self.get_object()
        feature_key = (
            ModelRoutingPolicy.FeatureKey.SCREENSHOT_ANALYSIS
            if document.source_type == RequirementDocument.SourceType.SCREENSHOT
            else ModelRoutingPolicy.FeatureKey.REQUIREMENT_ANALYSIS
        )
        required = required_model_types(feature_key)
        models = ModelConfig.objects.filter(
            is_active=True,
            model_type__in=required,
        ).order_by("priority", "name")
        try:
            route = ModelRouteResolver().resolve(feature_key)
            effective = route.primary.config if route.primary else None
            effective_source = route.primary.source if route.primary else ""
            route_error = route.failure_reason
            route_diagnostics = route.as_dict()
        except ModelRouteError as exc:
            effective = None
            effective_source = ""
            route_error = str(exc)
            route_diagnostics = {"available": False, "failure_reason": route_error}
        return Response({
            "feature_key": feature_key,
            "required_model_types": list(required),
            "models": SafeModelSummarySerializer(models, many=True).data,
            "effective_model": SafeModelSummarySerializer(effective).data if effective else None,
            "effective_source": effective_source,
            "route_error": route_error,
            "route": route_diagnostics,
        })

    @action(detail=True, methods=("post",))
    def parse(self, request, pk=None):
        """Parse the selected source and advance it to the analysis stage."""
        document = self.get_object()
        self._require_manager(document)
        try:
            parse_requirement_document(document)
        except DocumentParseError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        skill = SkillExecutionService().execute(
            "requirement_analysis",
            {"user_input": document.content_text or document.title, "project_id": str(document.project_id)},
        )
        data = self.get_serializer(document).data
        data["skill_execution"] = skill.as_dict() if skill else None
        return Response(data)

    @action(detail=True, methods=("post",))
    def analyze(self, request, pk=None):
        """Persist a new deep analysis result while retaining history."""
        document = self.get_object()
        self._require_manager(document)
        feature_key = (
            ModelRoutingPolicy.FeatureKey.SCREENSHOT_ANALYSIS
            if document.source_type == RequirementDocument.SourceType.SCREENSHOT
            else ModelRoutingPolicy.FeatureKey.REQUIREMENT_ANALYSIS
        )
        preferred_model_name = self._preferred_model_name(request, feature_key)
        try:
            analyze_requirement_document(document, preferred_model_name=preferred_model_name)
        except RequirementAnalysisError as exc:
            return self._analysis_failure_response(document, exc)
        document.refresh_from_db()
        skill = SkillExecutionService().execute(
            "requirement_analysis",
            {"user_input": document.content_text or document.title, "project_id": str(document.project_id)},
        )
        data = self.get_serializer(document).data
        data["skill_execution"] = skill.as_dict() if skill else None
        return Response(data)

    @action(detail=True, methods=("post",))
    def linkages(self, request, pk=None):
        """Identify and persist cross-module linkage scenarios."""
        document = self.get_object()
        self._require_manager(document)
        analysis = document.analyses.order_by("-created_at").first()
        if analysis is None:
            raise ValidationError({"detail": "请先完成需求深度分析。"})
        try:
            updated = identify_document_linkages(analysis)
        except LinkageAnalysisError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(RequirementAnalysisSerializer(updated).data)

    @action(detail=True, methods=("post",), url_path="clear-analysis")
    def clear_analysis(self, request, pk=None):
        """Clear analysis history while preserving the requirement source."""
        document = self.get_object()
        self._require_manager(document)
        result = RequirementAnalysisRecordService().clear_records(document)
        document.refresh_from_db()
        data = self.get_serializer(document).data
        data.update(result)
        return Response(data)

    @action(detail=True, methods=("post",), url_path="screenshot-analysis")
    def screenshot_analysis(self, request, pk=None):
        """Run visual analysis through the model runtime or an explicit OCR baseline."""
        document = self.get_object()
        self._require_manager(document)
        if document.source_type != RequirementDocument.SourceType.SCREENSHOT:
            raise ValidationError({"detail": "只有截图来源支持截图识别分析。"})
        feature_key = ModelRoutingPolicy.FeatureKey.SCREENSHOT_ANALYSIS
        preferred_model_name = self._preferred_model_name(request, feature_key)
        try:
            route = ModelRouteResolver().resolve(
                feature_key,
                task_type="screenshot",
                preferred_name=preferred_model_name,
            )
        except ModelRouteError as exc:
            raise ValidationError({"detail": str(exc), "code": "model_capability_mismatch"}) from exc

        if not document.file_path:
            document.visual_analysis_report = {
                "status": "failed",
                "analysis_method": "unavailable",
                "code": "image_required",
                "warnings": ["截图视觉分析需要图片文件；当前仅有 OCR 正文。"],
            }
            document.save(update_fields=("visual_analysis_report",))
            raise ValidationError({"detail": "截图文件不存在，请重新导入图片后执行视觉分析。", "code": "image_required"})

        path = Path(document.file_path)
        if not path.is_file():
            raise ValidationError({"detail": "截图文件不存在，请重新导入图片。", "code": "image_file_missing"})
        try:
            file_size = path.stat().st_size
        except OSError as exc:
            raise ValidationError({"detail": "截图文件无法读取，请重新导入图片。", "code": "image_unreadable"}) from exc
        if file_size > requirement_document_max_bytes():
            raise ValidationError({"detail": f"截图超过{requirement_document_limit_label()}限制。", "code": "image_file_too_large"})
        try:
            image_bytes = path.read_bytes()
        except OSError as exc:
            raise ValidationError({"detail": "截图文件无法读取，请重新导入图片。", "code": "image_unreadable"}) from exc

        evidence = list(document.parse_evidence) if isinstance(document.parse_evidence, list) else []
        if not evidence:
            try:
                evidence = list(parse_file(path).evidence)
            except DocumentParseError:
                evidence = []
        if route.available:
            mime_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix.casefold(), "image/png")
            try:
                report = RequirementModelAdapter().analyze_visual(
                    text=document.content_text,
                    evidence=evidence,
                    image_bytes=image_bytes,
                    image_mime_type=mime_type,
                    project_name=document.project.name,
                    preferred_model_name=preferred_model_name,
                )
                report = {
                    **report,
                    "status": "completed",
                    "analysis_method": "model_verified",
                    "model_status": "verified",
                    "model_route": route.as_dict(),
                    "call_stage": "screenshot_analysis",
                }
            except ModelAnalysisError as exc:
                report = {
                    "status": "failed",
                    "analysis_method": "model_partial" if exc.partial_payload else "model_failed",
                    "model_status": "partial" if exc.partial_payload else "failed",
                    "model_route": route.as_dict(),
                    "call_stage": "screenshot_analysis",
                    "error_code": exc.code,
                    "retryable": exc.code not in {"auth_failed", "forbidden", "model_capability_mismatch", "protocol_not_supported"},
                    "structured_generation": {"status": "partial", "segments": list(exc.structured_trace)},
                    "warnings": [str(exc)],
                }
                document.visual_analysis_report = report
                document.status = RequirementDocument.Status.FAILED
                document.save(update_fields=("visual_analysis_report", "status"))
                response_status = status.HTTP_502_BAD_GATEWAY if exc.code not in {"model_capability_mismatch", "protocol_not_supported"} else status.HTTP_400_BAD_REQUEST
                return Response({"detail": str(exc), "code": exc.code, "status": "partial" if exc.partial_payload else "failed", "retryable": report["retryable"], "document_status": document.status, "visual_analysis_report": report}, status=response_status)
        else:
            try:
                report = analyze_screenshot_file(document.file_path).as_dict()
            except DocumentParseError as exc:
                failed_report = {
                    "status": "failed",
                    "analysis_method": "deterministic_ocr_baseline",
                    "model_status": "not_configured",
                    "model_route": route.as_dict(),
                    "call_stage": "screenshot_analysis",
                    "error_code": "image_parse_failed",
                    "retryable": True,
                    "warnings": [str(exc)],
                }
                document.visual_analysis_report = failed_report
                document.status = RequirementDocument.Status.FAILED
                document.save(update_fields=("visual_analysis_report", "status"))
                return Response(
                    {"detail": str(exc), "code": "image_parse_failed", "status": "failed", "retryable": True, "document_status": document.status, "visual_analysis_report": failed_report},
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            report.update({
                "status": "completed",
                "analysis_method": "deterministic_ocr_baseline",
                "model_status": "not_configured",
                "model_route": route.as_dict(),
                "call_stage": "screenshot_analysis",
                "retryable": False,
            })
        skill = SkillExecutionService().execute(
            "ui_test",
            {"user_input": document.title, "image": document.file_path, "project_id": str(document.project_id)},
        )
        report["skill_execution"] = skill.as_dict() if skill else None
        document.visual_analysis_report = report
        document.save(update_fields=("visual_analysis_report",))
        return Response(report)


class RequirementAnalysisViewSet(viewsets.ReadOnlyModelViewSet):
    """Read structured analyses within visible project boundaries."""

    serializer_class = RequirementAnalysisSerializer
    permission_classes = (RequirementPermission,)

    def get_queryset(self):
        """Filter analysis results through their document project."""
        queryset = RequirementAnalysis.objects.select_related("document", "document__project")
        if not is_platform_admin(self.request.user):
            queryset = queryset.filter(document__project__memberships__user=self.request.user) | queryset.filter(document__project__created_by=self.request.user)
        document = self.request.query_params.get("document")
        if document:
            queryset = queryset.filter(document_id=document)
        return queryset.distinct()
