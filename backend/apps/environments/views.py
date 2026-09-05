"""Project-isolated CRUD for testing environments."""
from typing import Any
from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet
from rest_framework import serializers, viewsets
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.request import Request
from apps.environments.health import check_environment
from apps.environments.models import Environment
from apps.environments.permissions import EnvironmentPermission
from apps.environments.serializers import EnvironmentSerializer
from apps.projects.permissions import is_platform_admin
from core.utils.crypto import SecretDecryptionError


class EnvironmentViewSet(viewsets.ModelViewSet):
    """List only visible environments and enforce object write permissions."""
    serializer_class = EnvironmentSerializer
    permission_classes = (EnvironmentPermission,)
    lookup_value_regex = "[0-9a-fA-F-]{36}"

    @action(detail=True, methods=("post",), url_path="health-check")
    def health_check(self, request: Request, pk: str | None = None) -> Response:
        """Run an authorized manual probe and return safe updated metadata."""
        environment = check_environment(self.get_object())
        return Response(self.get_serializer(environment).data)

    def get_queryset(self) -> QuerySet[Environment]:
        """Validate filter identifiers and retain project isolation."""
        queryset = Environment.objects.select_related("project")
        if not is_platform_admin(self.request.user):
            queryset = queryset.filter(project__memberships__user=self.request.user)
        project = self.request.query_params.get("project")
        if project is not None:
            project_id = serializers.UUIDField().run_validation(project)
            queryset = queryset.filter(project_id=project_id)
        return queryset.distinct()

    def handle_exception(self, exc: Exception) -> Response:
        """Return an actionable generic response for unavailable encryption."""
        if isinstance(exc, (SecretDecryptionError, ImproperlyConfigured)):
            return Response({"detail": "环境配置加密服务不可用，请联系管理员检查密钥配置。"}, status=503)
        return super().handle_exception(exc)
