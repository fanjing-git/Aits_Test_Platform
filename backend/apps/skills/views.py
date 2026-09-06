from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
import base64
import binascii
from django.db.models import Q
from apps.projects.permissions import is_platform_admin, project_role
from apps.skills.models import Skill, SkillInstallation, SkillPermissionAudit
from apps.skills.permissions import SkillAuditPermission, SkillInstallationPermission, SkillPermission
from apps.skills.serializers import SkillInstallationSerializer, SkillPermissionAuditSerializer, SkillSerializer
from apps.skills.installation import (
    SkillInstallationError,
    approve_installation,
    install_verified,
    request_installation,
    rollback_installation,
    uninstall_installation,
    verify_installation,
)
from apps.skills.sources import SkillSourceError, discover_skill_manifest
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


class SkillInstallationViewSet(viewsets.ModelViewSet):
    """Administrator API for controlled third-party Skill lifecycle actions."""

    serializer_class = SkillInstallationSerializer
    permission_classes = (SkillInstallationPermission,)
    http_method_names = ("get", "post", "head", "options")

    def get_queryset(self):
        """Return installation metadata with related user and Skill labels loaded."""
        return SkillInstallation.objects.select_related("skill", "requested_by", "approved_by", "installed_by")

    @staticmethod
    def _failure(exc: Exception) -> Response:
        """Return a safe client-facing lifecycle error."""
        return Response({"detail": str(exc), "status": "failed"}, status=status.HTTP_400_BAD_REQUEST)

    def create(self, request, *args, **kwargs):
        """Validate source metadata and create a pending installation request."""
        payload = request.data if isinstance(request.data, dict) else {}
        manifest = payload.get("manifest")
        address = payload.get("source_url") or payload.get("address")
        source = payload.get("source_type") or payload.get("source")
        try:
            normalized = discover_skill_manifest(address, manifest, source=source)
            installation = request_installation(normalized, requested_by=request.user)
        except (SkillSourceError, SkillInstallationError, TypeError, AttributeError) as exc:
            return self._failure(exc)
        return Response(self.get_serializer(installation).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=("post",))
    def verify(self, request, pk=None):
        """Verify a caller-provided artifact fixture without downloading or executing code."""
        installation = self.get_object()
        encoded = request.data.get("artifact_base64")
        if not isinstance(encoded, str) or not encoded:
            return self._failure(SkillInstallationError("artifact_base64 is required for controlled verification"))
        try:
            artifact = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            return self._failure(SkillInstallationError("artifact_base64 is invalid"))
        try:
            updated = verify_installation(
                installation,
                artifact,
                artifact_version=request.data.get("artifact_version"),
                observed_commit_hash=request.data.get("observed_commit_hash"),
            )
        except SkillInstallationError as exc:
            return self._failure(exc)
        return Response(self.get_serializer(updated).data)

    def _transition(self, request, action_name):
        installation = self.get_object()
        handlers = {
            "approve": lambda: approve_installation(installation, request.user),
            "install": lambda: install_verified(installation, request.user),
            "rollback": lambda: rollback_installation(installation, request.user),
            "uninstall": lambda: uninstall_installation(installation, request.user),
        }
        try:
            updated = handlers[action_name]()
        except SkillInstallationError as exc:
            return self._failure(exc)
        return Response(self.get_serializer(updated).data)

    @action(detail=True, methods=("post",))
    def approve(self, request, pk=None):
        """Approve a verified installation request."""
        return self._transition(request, "approve")

    @action(detail=True, methods=("post",))
    def install(self, request, pk=None):
        """Mark an approved installation active without importing package code."""
        return self._transition(request, "install")

    @action(detail=True, methods=("post",))
    def rollback(self, request, pk=None):
        """Roll back a verified or installed package and disable its Skill."""
        return self._transition(request, "rollback")

    @action(detail=True, methods=("post",))
    def uninstall(self, request, pk=None):
        """Uninstall an active package while retaining its audit record."""
        return self._transition(request, "uninstall")
