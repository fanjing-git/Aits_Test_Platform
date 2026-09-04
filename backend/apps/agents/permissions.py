"""Project-aware permissions for agent configuration APIs."""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.projects.models import ProjectMember
from apps.projects.permissions import is_platform_admin, project_role


def can_edit_agents(user, project) -> bool:
    return is_platform_admin(user) or project_role(user, project) in {
        ProjectMember.Role.OWNER,
        ProjectMember.Role.MANAGER,
    }


class AgentObjectPermission(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if is_platform_admin(request.user):
            return True
        role = project_role(request.user, obj.project)
        if request.method in SAFE_METHODS:
            return role is not None
        if request.method == "DELETE":
            return role == ProjectMember.Role.OWNER
        return role in {ProjectMember.Role.OWNER, ProjectMember.Role.MANAGER}
