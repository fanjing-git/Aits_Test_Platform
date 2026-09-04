"""Object-level authorization for project collaboration."""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.projects.models import Project, ProjectMember
from apps.users.models import UserProfile


def is_platform_admin(user) -> bool:
    return getattr(getattr(user, "profile", None), "role", None) == UserProfile.Role.ADMIN


def project_role(user, project: Project) -> str | None:
    return ProjectMember.objects.filter(project=project, user=user).values_list(
        "role", flat=True
    ).first()


def can_manage_members(user, project: Project) -> bool:
    return is_platform_admin(user) or project_role(user, project) in {
        ProjectMember.Role.OWNER,
        ProjectMember.Role.MANAGER,
    }


class ProjectObjectPermission(BasePermission):
    """Members may read; owners/managers edit; owners or admins delete."""

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj: Project) -> bool:
        if is_platform_admin(request.user):
            return True
        role = project_role(request.user, obj)
        if request.method in SAFE_METHODS:
            return role is not None
        if request.method == "DELETE":
            return role == ProjectMember.Role.OWNER
        return role in {ProjectMember.Role.OWNER, ProjectMember.Role.MANAGER}
