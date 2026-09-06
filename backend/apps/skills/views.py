from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from apps.projects.permissions import is_platform_admin, project_role
from apps.skills.models import Skill, SkillPermissionAudit
from apps.skills.permissions import SkillAuditPermission, SkillPermission
from apps.skills.serializers import SkillPermissionAuditSerializer, SkillSerializer
from apps.skills.runtime import execute_skill, SkillRuntimeError

class SkillViewSet(viewsets.ModelViewSet):
    """CRUD and lifecycle API for global and project Skills."""
    serializer_class = SkillSerializer; permission_classes = (SkillPermission,)
    def get_queryset(self):
        """Return only global or project-visible Skills."""
        qs = Skill.objects.select_related('project','created_by')
        if is_platform_admin(self.request.user): return qs
        return qs.filter(Q(project__isnull=True) | Q(project__memberships__user=self.request.user)).distinct()
    def perform_update(self, serializer):
        """Enforce scoped management before saving changes."""
        self.check_object_permissions(self.request, self.get_object()); serializer.save()
    def perform_destroy(self, instance):
        """Enforce scoped management before deletion."""
        self.check_object_permissions(self.request, instance); instance.delete()
    @action(detail=True, methods=('post',))
    def toggle(self, request, pk=None):
        """Toggle enabled/disabled state with permission checks."""
        skill = self.get_object(); self.check_object_permissions(request, skill); skill.status = Skill.Status.DISABLED if skill.status == Skill.Status.ENABLED else Skill.Status.ENABLED; skill.save(update_fields=('status','updated_at')); return Response(self.get_serializer(skill).data)
    @action(detail=True, methods=('post',))
    def execute(self, request, pk=None):
        """Execute only through the controlled custom runtime boundary."""
        skill = self.get_object()
        self.check_object_permissions(request, skill)
        try:
            result = execute_skill(skill, request.data.get('input', request.data))
        except SkillRuntimeError as exc:
            return Response({'detail': str(exc), 'status': 'failed'}, status=400)
        return Response({'status': 'completed', 'result': result})


class SkillPermissionAuditViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only administrator view of permission decisions."""

    serializer_class = SkillPermissionAuditSerializer
    permission_classes = (SkillAuditPermission,)

    def get_queryset(self):
        """Return newest audit decisions with safe related labels."""
        queryset = SkillPermissionAudit.objects.select_related("installation", "actor")
        installation_id = self.request.query_params.get("installation")
        if installation_id:
            queryset = queryset.filter(installation_id=installation_id)
        return queryset
