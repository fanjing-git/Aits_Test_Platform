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

    def create(self, request, *args, **kwargs):
        """Generate a new five-round record from the latest document analysis."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = serializer.validated_data["document"]
        if not can_manage_requirements(request.user, document.project):
            raise PermissionDenied("当前项目角色不能生成测试用例。")
        try:
            record = generate_document_cases(document)
        except CaseGenerationError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(self.get_serializer(record).data, status=201)

    @action(detail=True, methods=("post",))
    def review(self, request, pk=None):
        """Run and persist the five-round case review."""
        record = self.get_object()
        if not can_manage_requirements(request.user, record.project):
            raise PermissionDenied("当前项目角色不能评审测试用例。")
        try:
            record = review_generation_record(record)
        except CaseReviewError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(self.get_serializer(record).data)

    @action(detail=True, methods=("post",))
    def select(self, request, pk=None):
        """Persist automation suitability and aggregate counts."""
        record = self.get_object()
        if not can_manage_requirements(request.user, record.project):
            raise PermissionDenied("当前项目角色不能筛选测试用例。")
        try:
            record = select_generation_record(record)
        except CaseSelectionError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(self.get_serializer(record).data)
