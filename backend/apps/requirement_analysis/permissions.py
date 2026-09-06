"""Project-scoped permissions for requirement analysis assets."""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.projects.permissions import is_platform_admin, project_role


def can_manage_requirements(user, project) -> bool:
    """Return whether a user may create or change requirement assets."""
    return is_platform_admin(user) or project_role(user, project) in {"owner", "manager"} or getattr(project, "created_by_id", None) == getattr(user, "pk", None)


class RequirementPermission(BasePermission):
    """Allow project members to read and managers to change requirements."""

    def has_permission(self, request, view) -> bool:
        """Reject anonymous requests before resolving project objects."""
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj) -> bool:
        """Apply project membership and write capability checks."""
        if is_platform_admin(request.user):
            return True
        project = getattr(obj, "project", None)
        if project is None and getattr(obj, "document", None) is not None:
            project = obj.document.project
        if project is None or (project_role(request.user, project) is None and getattr(project, "created_by_id", None) != getattr(request.user, "pk", None)):
            return False
        return request.method in SAFE_METHODS or can_manage_requirements(request.user, project)
