from rest_framework.permissions import BasePermission
from apps.projects.permissions import is_platform_admin, project_role
from apps.skills.models import SkillInstallation, SkillPermissionAudit
from apps.skills.sources import PERMISSION_KEYS
from typing import Any, Mapping


class SkillPermissionError(PermissionError):
    """Raised when a third-party Skill attempts an unavailable capability."""


def _declared_permissions(installation: SkillInstallation) -> dict[str, bool]:
    """Read a normalized manifest permission map and fail closed on malformed data."""
    value = installation.manifest.get("permissions") if isinstance(installation.manifest, dict) else None
    if not isinstance(value, dict):
        return {key: False for key in PERMISSION_KEYS}
    return {key: value.get(key) is True for key in PERMISSION_KEYS}


def enforce_skill_permission(
    installation: SkillInstallation,
    permission: str,
    *,
    actor: Any | None = None,
    context: Mapping[str, Any] | None = None,
) -> bool:
    """Authorize one capability and persist an allow/deny audit decision.

    Only permissions explicitly approved in the installed manifest are allowed;
    administrator identity never bypasses the manifest boundary. Context values
    are reduced to field names so secrets cannot enter the audit table.
    """
    if permission not in PERMISSION_KEYS:
        raise SkillPermissionError("unsupported Skill permission")
    declared = _declared_permissions(installation)
    allowed = installation.status == SkillInstallation.Status.INSTALLED and declared[permission]
    reason = "approved manifest permission" if allowed else "permission denied by installation policy"
    keys = sorted(str(key) for key in context.keys()) if isinstance(context, Mapping) else []
    try:
        SkillPermissionAudit.objects.create(
            installation=installation,
            permission=permission,
            allowed=allowed,
            reason=reason,
            context_keys=keys,
            actor=actor,
        )
    except Exception as exc:
        raise SkillPermissionError("permission decision could not be audited") from exc
    if not allowed:
        raise SkillPermissionError(f"Skill permission denied: {permission}")
    return True


class SkillPermissionGuard:
    """Small runtime guard passed to a Skill instead of raw privileged clients."""

    def __init__(self, installation: SkillInstallation, actor: Any | None = None) -> None:
        self.installation = installation
        self.actor = actor

    def require(self, permission: str, *, context: Mapping[str, Any] | None = None) -> None:
        """Require an approved capability before the caller performs an action."""
        enforce_skill_permission(self.installation, permission, actor=self.actor, context=context)


check_skill_permission = enforce_skill_permission

class SkillPermission(BasePermission):
    """Allow public Skill reads and scoped management for authorized users."""
    def has_permission(self, request, view):
        """Require authentication for every Skill endpoint."""
        return bool(request.user and request.user.is_authenticated)
    def has_object_permission(self, request, view, obj):
        """Restrict writes to platform admins or project managers."""
        if request.method in ('GET', 'HEAD', 'OPTIONS'): return is_platform_admin(request.user) or obj.project_id is None or project_role(request.user, obj.project) is not None
        return is_platform_admin(request.user) or (obj.project_id is not None and project_role(request.user, obj.project) in {'owner', 'manager'})


class SkillAuditPermission(BasePermission):
    """Allow only platform administrators to inspect permission audit entries."""

    def has_permission(self, request, view) -> bool:
        """Require authentication and the platform administrator role."""
        return bool(request.user and request.user.is_authenticated and is_platform_admin(request.user))
