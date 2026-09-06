"""REST endpoints for requirement ingestion, analysis and linkages."""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.projects.permissions import is_platform_admin
from apps.requirement_analysis.analyzer import RequirementAnalysisError, analyze_requirement_document
from apps.requirement_analysis.linkages import LinkageAnalysisError, identify_document_linkages
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument
from apps.requirement_analysis.parser import DocumentParseError, parse_requirement_document
from apps.requirement_analysis.permissions import RequirementPermission, can_manage_requirements
from apps.requirement_analysis.serializers import RequirementAnalysisSerializer, RequirementDocumentSerializer


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
        try:
            analyze_requirement_document(document)
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
