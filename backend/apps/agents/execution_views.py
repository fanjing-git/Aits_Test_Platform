"""REST endpoints for persisted agent execution state and controls."""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.agents.execution import AgentExecutionError, AgentExecutionService
from apps.agents.models import AgentExecution
from apps.agents.permissions import AgentExecutionObjectPermission
from apps.agents.serializers import AgentExecutionSerializer
from apps.projects.permissions import is_platform_admin


class AgentExecutionViewSet(viewsets.ReadOnlyModelViewSet):
    """Expose project-visible execution history and safe lifecycle controls."""

    serializer_class = AgentExecutionSerializer
    permission_classes = (AgentExecutionObjectPermission,)

    def get_queryset(self):
        """Return only executions visible to the current project member."""
        queryset = AgentExecution.objects.select_related("agent", "project", "requested_by")
        if is_platform_admin(self.request.user):
            visible = queryset
        else:
            visible = queryset.filter(project__memberships__user=self.request.user).distinct()
        agent_id = self.request.query_params.get("agent")
        project_id = self.request.query_params.get("project")
        if agent_id:
            visible = visible.filter(agent_id=agent_id)
        if project_id:
            visible = visible.filter(project_id=project_id)
        return visible

    def _control(self, request, signal):
        """Apply a pause/cancel request with stable client errors."""
        execution = self.get_object()
        try:
            result = AgentExecutionService().request_interrupt(execution, request.user, signal)
        except PermissionError as exc:
            raise PermissionDenied(str(exc)) from exc
        except AgentExecutionError as exc:
            raise ValidationError({"detail": str(exc), "code": exc.code}) from exc
        return Response(self.get_serializer(result).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=("post",))
    def pause(self, request, pk=None):
        """Pause a pending or running execution."""
        return self._control(request, "pause")

    @action(detail=True, methods=("post",))
    def cancel(self, request, pk=None):
        """Cancel a pending or running execution."""
        return self._control(request, "cancel")

    @action(detail=True, methods=("post",))
    def resume(self, request, pk=None):
        """Resume an execution paused by the user or an interrupt signal."""
        execution = self.get_object()
        try:
            result = AgentExecutionService().resume(execution, request.user)
        except PermissionError as exc:
            raise PermissionDenied(str(exc)) from exc
        except AgentExecutionError as exc:
            raise ValidationError({"detail": str(exc), "code": exc.code}) from exc
        return Response(self.get_serializer(result).data, status=status.HTTP_200_OK)
