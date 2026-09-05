"""Layer platform capabilities over project membership."""
from typing import Any
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView
from apps.projects.models import Project, ProjectMember
from apps.projects.permissions import is_platform_admin, project_role
from apps.users.permissions import PlatformAction, get_permission_scope, get_user_role
from apps.environments.models import Environment


def can_configure_environment(user: Any, project: Project) -> bool:
    """Require configuration capability and a project management role."""
    return is_platform_admin(user) or (
        get_permission_scope(get_user_role(user), PlatformAction.CONFIGURE_ENVIRONMENT) is not None
        and project_role(user, project) in {ProjectMember.Role.OWNER, ProjectMember.Role.MANAGER}
    )


class EnvironmentPermission(BasePermission):
    """Allow project reads and capability-gated configuration writes."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        """Reject unauthenticated access before resolving resources."""
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request: Request, view: APIView, obj: Environment) -> bool:
        """Apply both project boundaries and platform write capability."""
        if request.method in SAFE_METHODS:
            return is_platform_admin(request.user) or project_role(request.user, obj.project) is not None
        return can_configure_environment(request.user, obj.project)
