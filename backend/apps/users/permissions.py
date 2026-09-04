"""Role and operation permissions shared by platform APIs."""

from enum import StrEnum
from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.users.models import UserProfile


class PlatformAction(StrEnum):
    """Stable operation names used by API views when declaring access rules."""

    CREATE_AGENT = "create_agent"
    CREATE_CASE = "create_case"
    EXECUTE_TEST = "execute_test"
    VIEW_REPORT = "view_report"
    MANAGE_USERS = "manage_users"
    CONFIGURE_ENVIRONMENT = "configure_environment"
    MANAGE_GIT_INTEGRATION = "manage_git_integration"
    CONFIGURE_NOTIFICATIONS = "configure_notifications"
    REVIEW_KNOWLEDGE = "review_knowledge"


class PermissionScope(StrEnum):
    """Describe whether an allowed operation needs an object ownership check."""

    GLOBAL = "global"
    OWN_MODULE = "own_module"
    PERSONAL = "personal"


ROLE_ACTION_SCOPES: dict[str, dict[PlatformAction, PermissionScope]] = {
    UserProfile.Role.ADMIN: {
        action: PermissionScope.GLOBAL for action in PlatformAction
    },
    UserProfile.Role.TEST_LEADER: {
        PlatformAction.CREATE_AGENT: PermissionScope.GLOBAL,
        PlatformAction.CREATE_CASE: PermissionScope.GLOBAL,
        PlatformAction.EXECUTE_TEST: PermissionScope.GLOBAL,
        PlatformAction.VIEW_REPORT: PermissionScope.GLOBAL,
        PlatformAction.CONFIGURE_ENVIRONMENT: PermissionScope.GLOBAL,
        PlatformAction.MANAGE_GIT_INTEGRATION: PermissionScope.GLOBAL,
        PlatformAction.CONFIGURE_NOTIFICATIONS: PermissionScope.GLOBAL,
        PlatformAction.REVIEW_KNOWLEDGE: PermissionScope.GLOBAL,
    },
    UserProfile.Role.TESTER: {
        PlatformAction.CREATE_CASE: PermissionScope.GLOBAL,
        PlatformAction.EXECUTE_TEST: PermissionScope.GLOBAL,
        PlatformAction.VIEW_REPORT: PermissionScope.GLOBAL,
        PlatformAction.CONFIGURE_NOTIFICATIONS: PermissionScope.PERSONAL,
    },
    UserProfile.Role.DEVELOPER: {
        PlatformAction.EXECUTE_TEST: PermissionScope.OWN_MODULE,
        PlatformAction.VIEW_REPORT: PermissionScope.OWN_MODULE,
        PlatformAction.CONFIGURE_NOTIFICATIONS: PermissionScope.PERSONAL,
    },
    UserProfile.Role.VIEWER: {
        PlatformAction.VIEW_REPORT: PermissionScope.GLOBAL,
    },
}


def get_user_role(user: Any) -> str | None:
    """Return an authenticated user's platform role, or ``None`` safely."""
    if not getattr(user, "is_authenticated", False):
        return None
    try:
        return str(user.profile.role)
    except UserProfile.DoesNotExist:
        return None


def get_permission_scope(
    role: str | None,
    action: PlatformAction | str,
) -> PermissionScope | None:
    """Return the allowed scope for a role/action pair, denying unknown input."""
    if role is None:
        return None
    try:
        normalized_action = PlatformAction(action)
    except ValueError:
        return None
    return ROLE_ACTION_SCOPES.get(role, {}).get(normalized_action)


class HasPlatformPermission(BasePermission):
    """Authorize the operation declared by ``view.permission_action``."""

    message = "You do not have permission to perform this operation."

    def has_permission(self, request: Request, view: APIView) -> bool:
        """Allow authenticated users whose role contains the declared action."""
        action = getattr(view, "permission_action", None)
        if action is None:
            return False
        return get_permission_scope(get_user_role(request.user), action) is not None

    def has_object_permission(
        self,
        request: Request,
        view: APIView,
        obj: Any,
    ) -> bool:
        """Require a view-provided checker for personal or own-module access."""
        action = getattr(view, "permission_action", None)
        if action is None:
            return False
        scope = get_permission_scope(get_user_role(request.user), action)
        if scope is None:
            return False
        if scope is PermissionScope.GLOBAL:
            return True
        scope_checker = getattr(view, "has_permission_scope", None)
        if not callable(scope_checker):
            return False
        return bool(scope_checker(request, obj, scope))


class HasRolePermission(BasePermission):
    """Base class for endpoints restricted to one exact platform role."""

    required_role: str = ""

    def has_permission(self, request: Request, view: APIView) -> bool:
        """Allow only authenticated users with the configured exact role."""
        return get_user_role(request.user) == self.required_role


class IsAdminRole(HasRolePermission):
    """Allow platform administrators only."""

    required_role = UserProfile.Role.ADMIN


class IsTestLeaderRole(HasRolePermission):
    """Allow test leaders only."""

    required_role = UserProfile.Role.TEST_LEADER


class IsTesterRole(HasRolePermission):
    """Allow test engineers only."""

    required_role = UserProfile.Role.TESTER


class IsDeveloperRole(HasRolePermission):
    """Allow developers only."""

    required_role = UserProfile.Role.DEVELOPER


class IsViewerRole(HasRolePermission):
    """Allow visitors only."""

    required_role = UserProfile.Role.VIEWER
