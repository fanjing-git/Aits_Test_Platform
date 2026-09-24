"""REST endpoints for requirement ingestion, analysis and linkages."""

from pathlib import Path
from uuid import uuid4

from django.conf import settings
from core.task_state import task_runtime, utc_now
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
from apps.requirement_analysis.serializers import RequirementAnalysisConfirmationSerializer, RequirementAnalysisSerializer, RequirementDocumentSerializer, RequirementTestPointReviewSerializer
from apps.requirement_analysis.screenshot_analyzer import analyze_screenshot_file
from apps.requirement_analysis.services import RequirementAnalysisConfirmationError, RequirementAnalysisRecordService
from apps.requirement_analysis.tasks import run_requirement_analysis, set_requirement_runtime
from apps.skills.business_execution import BusinessSkillRunError, BusinessSkillRunService, business_skill_execution
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

    @action(detail=True, methods=("post",), url_path="review-requirement")
    def review_requirement(self, request, pk=None):
        """Execute the independent requirement-review Skill on the latest version."""
        document = self.get_object()
        self._require_manager(document)
        analysis = document.analyses.order_by("-created_at").first()
        if analysis is None:
            raise ValidationError({"detail": "请先完成需求分析。"})
        service = BusinessSkillRunService()
        try:
            run = service.start(
                user=request.user,
                project_id=document.project_id,
                workflow_key="requirement_review",
                operation="requirement_review",
                business_type="requirement_analysis",
                business_id=analysis.pk,
                input_snapshot={"document_id": str(document.pk), "analysis_id": str(analysis.pk), "analysis_fingerprint": analysis.analysis_fingerprint},
                node_id="requirement_review",
                skill_name="需求评审",
            )
            service.mark_running(run, "requirement_review")
            reviewed = RequirementAnalysisRecordService().review_latest_analysis(document)
            reviewed.review_run = run
            reviewed.save(update_fields=("review_run",))
            if reviewed.review_status != RequirementAnalysis.StageStatus.PASSED:
                raise RequirementAnalysisConfirmationError("需求评审未通过，请先修复结构映射或验收条件问题。")
            service.complete(run, "requirement_review", {
                "analysis_id": str(reviewed.pk), "review_status": reviewed.review_status,
                "issue_count": len((reviewed.review_report or {}).get("issues", [])),
            }, artifact_ref={"type": "requirement_review", "id": str(reviewed.pk)})
        except (BusinessSkillRunError, RequirementAnalysisConfirmationError) as exc:
            if "run" in locals():
                service.fail(run, "requirement_review", "review_failed", str(exc))
            raise ValidationError({"detail": str(exc)}) from exc
        document.refresh_from_db()
        payload = self.get_serializer(document).data
        payload["skill_execution"] = business_skill_execution(run, "需求评审")
        return Response(payload)

    @action(detail=True, methods=("post",), url_path="decompose-requirement")
    def decompose_requirement(self, request, pk=None):
        """Execute requirement decomposition only after the review gate passes."""
        document = self.get_object()
        self._require_manager(document)
        analysis = document.analyses.order_by("-created_at").first()
        if analysis is None:
            raise ValidationError({"detail": "请先完成需求分析和需求评审。"})
        service = BusinessSkillRunService()
        try:
            run = service.start(
                user=request.user,
                project_id=document.project_id,
                workflow_key="requirement_decomposition",
                operation="requirement_decomposition",
                business_type="requirement_analysis",
                business_id=analysis.pk,
                input_snapshot={"document_id": str(document.pk), "analysis_id": str(analysis.pk), "review_run_id": str(analysis.review_run_id or "")},
                node_id="requirement_decomposition",
                skill_name="需求拆解",
            )
            service.mark_running(run, "requirement_decomposition")
            decomposed = RequirementAnalysisRecordService().decompose_reviewed_analysis(document)
            decomposed.decomposition_run = run
            decomposed.save(update_fields=("decomposition_run",))
            service.complete(run, "requirement_decomposition", {
                "analysis_id": str(decomposed.pk), "decomposition_status": decomposed.decomposition_status,
                "module_count": len((decomposed.decomposition or {}).get("modules", [])),
                "function_count": len((decomposed.decomposition or {}).get("functions", [])),
                "flow_count": len((decomposed.decomposition or {}).get("business_flows", [])),
            }, artifact_ref={"type": "requirement_decomposition", "id": str(decomposed.pk)})
        except (BusinessSkillRunError, RequirementAnalysisConfirmationError) as exc:
            if "run" in locals():
                service.fail(run, "requirement_decomposition", "decomposition_failed", str(exc))
            raise ValidationError({"detail": str(exc)}) from exc
        document.refresh_from_db()
        payload = self.get_serializer(document).data
        payload["skill_execution"] = business_skill_execution(run, "需求拆解")
        return Response(payload)

    @action(detail=True, methods=("post",), url_path="review-test-points")
    def review_test_points(self, request, pk=None):
        """Persist selected reviewed test points without finalizing the analysis."""
        document = self.get_object()
        self._require_manager(document)
        review = RequirementTestPointReviewSerializer(data=request.data)
        review.is_valid(raise_exception=True)
        try:
            document = RequirementAnalysisRecordService().mark_test_points_reviewed(
                document,
                request.user,
                **review.validated_data,
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
        data = self.get_serializer(document).data
        data["skill_execution"] = {
            "skill": "需求分析",
            "version": "1.0.0",
            "status": "completed",
            "runtime": "document_parser",
            "message": "需求原文已解析；尚未启动需求分析业务父运行。",
        }
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
        raw_resume_round = request.data.get("resume_round", 1)
        try:
            resume_from_round = int(raw_resume_round or 1)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"resume_round": "恢复轮次必须是 1 到 5 的整数。"}) from exc
        if not 1 <= resume_from_round <= 5:
            raise ValidationError({"resume_round": "恢复轮次必须是 1 到 5 的整数。"})
        current_runtime = (document.analysis_baseline or {}).get("_task_runtime")
        if isinstance(current_runtime, dict) and current_runtime.get("status") in {"pending", "running", "cancel_requested"}:
            return Response({"detail": "当前需求分析任务仍在处理中，请等待完成或先取消。", "task_runtime": current_runtime}, status=status.HTTP_409_CONFLICT)
        try:
            business_run = BusinessSkillRunService().start(
                user=request.user,
                project_id=document.project_id,
                workflow_key="requirement_analysis",
                operation="requirement_analysis",
                business_type="requirement_document",
                business_id=document.pk,
                input_snapshot={
                    "document_id": str(document.pk),
                    "document_version": document.version,
                    "source_type": document.source_type,
                    "resume_from_round": resume_from_round,
                    "preferred_model_name": preferred_model_name or "",
                },
                node_id="requirement_analysis",
                skill_name="需求分析",
            )
        except BusinessSkillRunError as exc:
            return Response({"detail": str(exc), "code": "business_run_invalid"}, status=status.HTTP_409_CONFLICT)
        document.analysis_run = business_run
        document.save(update_fields=("analysis_run",))
        if not settings.CELERY_TASK_ALWAYS_EAGER:
            task_id = uuid4().hex
            runtime = task_runtime(
                task_id,
                "requirement_analysis",
                status="pending",
                current_step="排队中",
                current_round=max(0, resume_from_round - 1),
                completed_rounds=max(0, resume_from_round - 1),
            )
            set_requirement_runtime(document, runtime, status=RequirementDocument.Status.ANALYZING)
            try:
                run_requirement_analysis.apply_async(
                    args=[str(document.pk), preferred_model_name, resume_from_round, task_id, str(business_run.pk)],
                    task_id=task_id,
                )
            except Exception as exc:
                runtime.update({"status": "failed", "error_code": "task_enqueue_failed", "detail": str(exc)[:200]})
                set_requirement_runtime(document, runtime, status=RequirementDocument.Status.FAILED)
                BusinessSkillRunService().fail(business_run, "requirement_analysis", "task_enqueue_failed", "需求分析任务提交失败。")
                return Response({"detail": "分析任务提交失败，请稍后重试。", "code": "task_enqueue_failed", "task_runtime": runtime}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            document.refresh_from_db()
            return Response({"document": self.get_serializer(document).data, "task_runtime": runtime, "skill_execution": business_skill_execution(business_run, "需求分析")}, status=status.HTTP_202_ACCEPTED)
        try:
            BusinessSkillRunService().mark_running(business_run, "requirement_analysis")
            analysis = analyze_requirement_document(
                document,
                preferred_model_name=preferred_model_name,
                resume_from_round=resume_from_round,
            )
        except RequirementAnalysisError as exc:
            BusinessSkillRunService().fail(business_run, "requirement_analysis", exc.code, str(exc))
            return self._analysis_failure_response(document, exc)
        BusinessSkillRunService().complete(
            business_run,
            "requirement_analysis",
            {
                "analysis_id": str(analysis.pk),
                "quality_status": analysis.quality_status,
                "module_count": len(analysis.modules or []),
                "function_count": len(analysis.functions or []),
                "test_point_count": len(analysis.test_points or []),
            },
            artifact_ref={"type": "requirement_analysis", "id": str(analysis.pk)},
        )
        document.refresh_from_db()
        data = self.get_serializer(document).data
        data["skill_execution"] = business_skill_execution(business_run, "需求分析")
        return Response(data)

    @action(detail=True, methods=("post",), url_path="cancel-analysis")
    def cancel_analysis(self, request, pk=None):
        """Request cooperative cancellation of a queued or running analysis task."""
        document = self.get_object()
        self._require_manager(document)
        runtime = dict((document.analysis_baseline or {}).get("_task_runtime") or {})
        if runtime.get("status") not in {"pending", "running", "cancel_requested"}:
            raise ValidationError({"detail": "当前没有可取消的需求分析任务。"})
        runtime.update({"status": "cancel_requested", "cancel_requested": True, "current_step": "正在取消", "updated_at": utc_now()})
        set_requirement_runtime(document, runtime, status=RequirementDocument.Status.ANALYZING)
        task_id = runtime.get("task_id")
        if task_id:
            try:
                from config.celery_app import app
                app.control.revoke(str(task_id), terminate=False)
            except Exception:
                pass
        return Response({"document_status": document.status, "task_runtime": runtime})

    @action(detail=True, methods=("post",), url_path="retry-round")
    def retry_round(self, request, pk=None):
        """Retry a failed or partial semantic round through the normal analysis contract."""
        return self.analyze(request, pk=pk)

    @action(detail=True, methods=("get",), url_path="analysis-progress")
    def analysis_progress(self, request, pk=None):
        """Return safe five-round progress and historical round summaries."""
        document = self.get_object()
        latest = document.analyses.order_by("-created_at").first()
        report = dict(latest.coverage_report or {}) if latest else {}
        runtime = dict(
            (document.analysis_baseline or {}).get("_task_runtime")
            or (document.analysis_baseline or {}).get("_last_task_runtime")
            or report.get("task_runtime")
            or {}
        )
        history = []
        for analysis in document.analyses.order_by("-created_at")[:20]:
            coverage = dict(analysis.coverage_report or {})
            history.append({
                "id": str(analysis.id),
                "created_at": analysis.created_at,
                "quality_status": analysis.quality_status,
                "round_count": coverage.get("round_count", 0),
                "completed_rounds": coverage.get("completed_rounds", 0),
                "round_execution_status": coverage.get("round_execution_status", "unknown"),
                "total_calls": coverage.get("total_calls", 0),
                "rounds": coverage.get("rounds", []),
            })
        return Response({
            "document": str(document.id),
            "document_status": document.status,
            "analysis_id": str(latest.id) if latest else None,
            "quality_status": latest.quality_status if latest else None,
            "round_progress": report.get("round_progress", {"current_round": 0, "total_rounds": 5, "status": "pending"}),
            "rounds": report.get("rounds", []),
            "task_runtime": runtime or None,
            "history": history,
        })

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
