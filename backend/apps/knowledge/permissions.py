"""Knowledge API project isolation and review permissions."""
from rest_framework.permissions import SAFE_METHODS, BasePermission
from apps.projects.permissions import is_platform_admin, project_role
from apps.projects.models import ProjectMember
from apps.knowledge.review import can_review

def can_manage(user, base) -> bool:
    """Allow administrators or project managers to change knowledge assets."""
    return is_platform_admin(user) or project_role(user, base.project) in {ProjectMember.Role.OWNER, ProjectMember.Role.MANAGER} if base.project_id else is_platform_admin(user)

class KnowledgePermission(BasePermission):
    """Allow visible bases to be read and managers to write."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)
    def has_object_permission(self, request, view, obj):
        base = obj if hasattr(obj, 'project_id') else obj.knowledge_base
        if request.method in SAFE_METHODS: return is_platform_admin(request.user) or (base.project_id and project_role(request.user, base.project) is not None)
        return can_manage(request.user, base)
