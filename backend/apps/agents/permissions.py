"""Project-aware permissions for agent configuration APIs."""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.projects.models import ProjectMember
from apps.projects.permissions import is_platform_admin, project_role
from apps.users.permissions import (
    PermissionScope,
    PlatformAction,
    get_permission_scope,
    get_user_role,
)


def can_edit_agents(user, project) -> bool:
    """Require the agent capability and a writable project membership."""
    return bool(
        is_platform_admin(user)
        or (
            project_role(user, project)
            in {ProjectMember.Role.OWNER, ProjectMember.Role.MANAGER}
            and get_permission_scope(
                get_user_role(user), PlatformAction.CREATE_AGENT
            )
            is not None
        )
    )


def can_execute_agent(user, agent) -> bool:
    """Require execution capability, project membership, and own-module scope."""
    if is_platform_admin(user):
        return True
    role = project_role(user, agent.project)
    if role not in {
        ProjectMember.Role.OWNER,
        ProjectMember.Role.MANAGER,
        ProjectMember.Role.MEMBER,
    }:
        return False
    scope = get_permission_scope(get_user_role(user), PlatformAction.EXECUTE_TEST)
    if scope is None:
        return False
    return scope is not PermissionScope.OWN_MODULE or agent.created_by_id == user.pk


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


class AgentExecutePermission(BasePermission):
    """Allow project members to run an active agent, with no config mutation."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        return can_execute_agent(request.user, obj)


class AgentExecutionObjectPermission(BasePermission):
    """Keep execution history project-scoped and controls owner/manager-scoped."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if is_platform_admin(request.user):
            return True
        if obj.project_id is None:
            return (
                obj.requested_by_id == request.user.pk
                and get_permission_scope(
                    get_user_role(request.user), PlatformAction.EXECUTE_TEST
                )
                is not None
            )
        role = project_role(request.user, obj.project)
        if request.method in SAFE_METHODS:
            return role is not None
        if obj.agent_id is None:
            return False
        return can_execute_agent(request.user, obj.agent)
