"""Project-scoped permissions for test assets and execution records."""

from typing import Any

from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request

from apps.projects.models import Project, ProjectMember
from apps.projects.permissions import is_platform_admin, project_role
from apps.users.permissions import PlatformAction, get_permission_scope, get_user_role


def can_view_test_asset(user: Any, project: Project) -> bool:
    """Allow authenticated project members, including read-only members, to read assets."""
    return bool(
        is_platform_admin(user)
        or project_role(user, project) is not None
    )


def can_write_test_case(user: Any, project: Project) -> bool:
    """Allow case authors with the platform capability and a writable project role."""
    role = project_role(user, project)
    return bool(
        is_platform_admin(user)
        or (
            role in {ProjectMember.Role.OWNER, ProjectMember.Role.MANAGER, ProjectMember.Role.MEMBER}
            and get_permission_scope(get_user_role(user), PlatformAction.CREATE_CASE) is not None
        )
    )


def can_execute_test(user: Any, project: Project) -> bool:
    """Allow project members whose platform role can execute tests to start a run."""
    role = project_role(user, project)
    return bool(
        is_platform_admin(user)
        or (
            role in {ProjectMember.Role.OWNER, ProjectMember.Role.MANAGER, ProjectMember.Role.MEMBER}
            and get_permission_scope(get_user_role(user), PlatformAction.EXECUTE_TEST) is not None
        )
    )


class TestAssetPermission(BasePermission):
    """Read project test assets for members and gate writes by operation."""

    def has_permission(self, request: Request, view: Any) -> bool:
        """Require authentication before any project lookup."""
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request: Request, view: Any, obj: Any) -> bool:
        """Apply project membership and the view's write capability to one object."""
        project = obj.project
        if request.method in SAFE_METHODS:
            return can_view_test_asset(request.user, project)
        checker = getattr(view, "can_write", None)
        return bool(callable(checker) and checker(request.user, project))
