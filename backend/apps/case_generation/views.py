"""REST endpoints for generation, review and automation selection."""

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.case_generation.generator import CaseGenerationError, generate_document_cases
from apps.case_generation.models import CaseGenerationRecord
from apps.case_generation.reviewer import CaseReviewError, review_generation_record
from apps.case_generation.selector import CaseSelectionError, select_generation_record
from apps.case_generation.serializers import CaseGenerationRecordSerializer
from apps.projects.permissions import is_platform_admin
from apps.configs.models import ModelConfig, ModelRoutingPolicy
from apps.configs.routing import ModelRouteError, ModelRouteResolver, required_model_types
from apps.configs.serializers import SafeModelSummarySerializer
from apps.requirement_analysis.permissions import RequirementPermission, can_manage_requirements


class CaseGenerationViewSet(viewsets.ModelViewSet):
    """Manage project-scoped generation records through the workbench API."""

    serializer_class = CaseGenerationRecordSerializer
    permission_classes = (RequirementPermission,)
    http_method_names = ("get", "post", "head", "options")

    def get_queryset(self):
        """Return only records in projects visible to the current user."""
        queryset = CaseGenerationRecord.objects.select_related("project", "document")
        if not is_platform_admin(self.request.user):
            queryset = queryset.filter(project__memberships__user=self.request.user) | queryset.filter(project__created_by=self.request.user)
        project = self.request.query_params.get("project")
        if project:
            queryset = queryset.filter(project_id=project)
        document = self.request.query_params.get("document")
        if document:
            queryset = queryset.filter(document_id=document)
        return queryset.distinct()

    @staticmethod
    def _preferred_model_name(request, feature_key: str) -> str | None:
        """Validate an optional per-run model choice against feature capability."""
        raw_id = request.data.get("model_config_id")
        if raw_id in (None, "", "null"):
            return None
        try:
            config_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"model_config_id": "模型配置编号无效。"}) from exc
        config = ModelConfig.objects.filter(pk=config_id, is_active=True).first()
        if config is None or config.model_type not in set(required_model_types(feature_key)):
            raise ValidationError({"model_config_id": "所选模型不存在、已停用或不支持此功能。"})
        return config.name

    @action(detail=False, methods=("get",), url_path="model-options")
    def model_options(self, request):
        """Return safe selectable models and the effective route for generation or review."""
        feature = request.query_params.get("feature", ModelRoutingPolicy.FeatureKey.CASE_GENERATION)
        if feature not in {ModelRoutingPolicy.FeatureKey.CASE_GENERATION, ModelRoutingPolicy.FeatureKey.CASE_REVIEW}:
            raise ValidationError({"feature": "功能必须是用例生成或用例评审。"})
        required = required_model_types(feature)
        models = ModelConfig.objects.filter(is_active=True, model_type__in=required).order_by("priority", "name")
        try:
            route = ModelRouteResolver().resolve(feature)
            effective = route.primary.config if route.primary else None
            effective_source = route.primary.source if route.primary else ""
            route_error = ""
        except ModelRouteError as exc:
            effective = None
            effective_source = ""
            route_error = str(exc)
        return Response({
            "feature_key": feature,
            "required_model_types": list(required),
            "models": SafeModelSummarySerializer(models, many=True).data,
            "effective_model": SafeModelSummarySerializer(effective).data if effective else None,
            "effective_source": effective_source,
            "route_error": route_error,
        })

    def create(self, request, *args, **kwargs):
        """Generate a new five-round record from the latest document analysis."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = serializer.validated_data["document"]
        if not can_manage_requirements(request.user, document.project):
            raise PermissionDenied("当前项目角色不能生成测试用例。")
        try:
            preferred_model_name = self._preferred_model_name(request, ModelRoutingPolicy.FeatureKey.CASE_GENERATION)
            record = generate_document_cases(document, preferred_model_name=preferred_model_name)
        except CaseGenerationError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(self.get_serializer(record).data, status=201)

    @action(detail=True, methods=("post",))
    def review(self, request, pk=None):
        """Run and persist the five-round case review."""
        record = self.get_object()
        if not can_manage_requirements(request.user, record.project):
            raise PermissionDenied("当前项目角色不能评审测试用例。")
        if record.review_rounds >= 5 and isinstance(record.review_report, dict) and "approved" in record.review_report:
            return Response(self.get_serializer(record).data)
        try:
            preferred_model_name = self._preferred_model_name(request, ModelRoutingPolicy.FeatureKey.CASE_REVIEW)
            record = review_generation_record(record, preferred_model_name=preferred_model_name)
        except CaseReviewError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(self.get_serializer(record).data)

    @action(detail=True, methods=("post",))
    def select(self, request, pk=None):
        """Persist automation suitability and aggregate counts."""
        record = self.get_object()
        if not can_manage_requirements(request.user, record.project):
            raise PermissionDenied("当前项目角色不能筛选测试用例。")
        if isinstance(record.coverage_report, dict) and isinstance(record.coverage_report.get("automation_selection"), dict):
            return Response(self.get_serializer(record).data)
        try:
            record = select_generation_record(record)
        except CaseSelectionError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(self.get_serializer(record).data)
