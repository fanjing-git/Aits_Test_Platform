from rest_framework.permissions import BasePermission
from django.core.exceptions import ValidationError as DjangoValidationError
from apps.projects.permissions import is_platform_admin, project_role
from apps.skills.models import SkillChain, SkillChainConfiguration, SkillChainRun, SkillInstallation, SkillPermissionAudit
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


def can_read_governance_audit(user: Any, target: Any) -> bool:
    """Restrict governance history to platform admins or managers of its project."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if is_platform_admin(user):
        return True
    configuration = target if isinstance(target, SkillChainConfiguration) else None
    chain = target if isinstance(target, SkillChain) else getattr(target, "chain", None)
    project = getattr(configuration, "project", None) if configuration is not None else None
    project = project or getattr(chain, "project", None)
    return bool(project is not None and project_role(user, project) in {"owner", "manager"})


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


class SkillInstallationPermission(BasePermission):
    """Allow only platform administrators to manage third-party installations."""

    def has_permission(self, request, view) -> bool:
        """Require an authenticated platform administrator for lifecycle APIs."""
        return bool(request.user and request.user.is_authenticated and is_platform_admin(request.user))

class SkillChainPermission(BasePermission):
    """Allow authenticated users to read visible chains and managers to edit them."""

    def has_permission(self, request, view) -> bool:
        """Require authentication for chain contracts."""
        return bool(request.user and request.user.is_authenticated)

    @staticmethod
    def _project(obj: SkillChain) -> Any | None:
        """Return the scope project for an object."""
        return getattr(obj, "project", None)

    def has_object_permission(self, request, view, obj) -> bool:
        """Apply the same global/project boundary as Skill definitions."""
        project = self._project(obj)
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return is_platform_admin(request.user) or project is None or project_role(request.user, project) is not None
        return is_platform_admin(request.user) or (project is not None and project_role(request.user, project) in {"owner", "manager"})


class SkillChainConfigurationPermission(BasePermission):
    """Protect config reads by project visibility and writes by manager scope."""

    def has_permission(self, request, view) -> bool:
        """Require authentication and precheck create-scope management rights."""
        if not request.user or not request.user.is_authenticated:
            return False
        action = getattr(view, "action", None)
        if request.method in ("GET", "HEAD", "OPTIONS") or action == "resolve":
            return True
        if request.method != "POST" or action != "create":
            return True
        if is_platform_admin(request.user):
            return True
        from apps.skills.models import SkillChain
        from apps.projects.models import Project

        layer = request.data.get("layer", "")
        if layer == SkillChainConfiguration.Layer.GLOBAL:
            return False
        project_id = request.data.get("project")
        if not project_id:
            chain_id = request.data.get("chain")
            try:
                project_id = SkillChain.objects.only("project_id").get(pk=chain_id).project_id
            except (SkillChain.DoesNotExist, ValueError, TypeError, DjangoValidationError):
                return False
        if not project_id:
            return False
        try:
            project = Project.objects.get(pk=project_id)
        except (Project.DoesNotExist, ValueError, TypeError, DjangoValidationError):
            return False
        return project_role(request.user, project) in {"owner", "manager"}

    @staticmethod
    def _project(obj: SkillChainConfiguration) -> Any | None:
        """Resolve the configuration project or owning chain project."""
        return obj.project or getattr(obj.chain, "project", None)

    def has_object_permission(self, request, view, obj) -> bool:
        """Allow visible reads and restrict writes to platform/project managers."""
        project = self._project(obj)
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return is_platform_admin(request.user) or project is None or project_role(request.user, project) is not None
        return is_platform_admin(request.user) or (project is not None and project_role(request.user, project) in {"owner", "manager"})


class SkillChainRunPermission(BasePermission):
    """Protect run snapshots while allowing project members to inspect visible runs."""

    def has_permission(self, request, view) -> bool:
        """Require authentication for run creation and controls."""
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj: SkillChainRun) -> bool:
        """Allow requesters or members of the run project to operate within scope."""
        if is_platform_admin(request.user) or obj.requested_by_id == request.user.pk:
            return True
        project = obj.project
        if project is None:
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return project_role(request.user, project) is not None
        return project_role(request.user, project) in {"owner", "manager"}
