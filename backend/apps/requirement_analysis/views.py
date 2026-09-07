"""REST endpoints for requirement ingestion, analysis and linkages."""

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
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument
from apps.requirement_analysis.parser import DocumentParseError, parse_requirement_document
from apps.requirement_analysis.permissions import RequirementPermission, can_manage_requirements
from apps.requirement_analysis.serializers import RequirementAnalysisSerializer, RequirementDocumentSerializer
from apps.requirement_analysis.screenshot_analyzer import analyze_screenshot_file


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
            route_error = ""
        except ModelRouteError as exc:
            effective = None
            effective_source = ""
            route_error = str(exc)
        return Response({
            "feature_key": feature_key,
            "required_model_types": list(required),
            "models": SafeModelSummarySerializer(models, many=True).data,
            "effective_model": SafeModelSummarySerializer(effective).data if effective else None,
            "effective_source": effective_source,
            "route_error": route_error,
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
        return Response(self.get_serializer(document).data)

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
            raise ValidationError({"detail": str(exc)}) from exc
        document.refresh_from_db()
        return Response(self.get_serializer(document).data)

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

    @action(detail=True, methods=("post",), url_path="screenshot-analysis")
    def screenshot_analysis(self, request, pk=None):
        """Return evidence-grounded screenshot observations for screenshot sources."""
        document = self.get_object()
        self._require_manager(document)
        if document.source_type != RequirementDocument.SourceType.SCREENSHOT:
            raise ValidationError({"detail": "只有截图来源支持截图识别分析。"})
        if not document.file_path:
            raise ValidationError({"detail": "截图文件不存在，请重新导入图片。"})
        try:
            report = analyze_screenshot_file(document.file_path).as_dict()
        except DocumentParseError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
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
