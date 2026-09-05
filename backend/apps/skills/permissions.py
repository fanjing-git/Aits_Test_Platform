from rest_framework.permissions import BasePermission
from apps.projects.permissions import is_platform_admin, project_role

class SkillPermission(BasePermission):
    """Allow public Skill reads and scoped management for authorized users."""
    def has_permission(self, request, view):
        """Require authentication for every Skill endpoint."""
        return bool(request.user and request.user.is_authenticated)
    def has_object_permission(self, request, view, obj):
        """Restrict writes to platform admins or project managers."""
        if request.method in ('GET', 'HEAD', 'OPTIONS'): return is_platform_admin(request.user) or obj.project_id is None or project_role(request.user, obj.project) is not None
        return is_platform_admin(request.user) or (obj.project_id is not None and project_role(request.user, obj.project) in {'owner', 'manager'})
