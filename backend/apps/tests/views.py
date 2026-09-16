"""REST endpoints for project test cases and API execution runs."""

from typing import Any

from django.db.models import QuerySet
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.projects.permissions import is_platform_admin
from apps.tests.models import TestCase, TestRun
from apps.tests.permissions import TestAssetPermission, can_execute_test, can_write_test_case, can_view_test_asset
from apps.tests.serializers import TestCaseSerializer, TestResultSerializer, TestRunSerializer
from apps.tests.services import execute_test_run


class _ProjectScopedViewSet(viewsets.ModelViewSet):
    """Share strict project filtering and readable invalid-filter responses."""

    permission_classes = (TestAssetPermission,)
    lookup_value_regex = r"[0-9a-fA-F-]{36}"

    def _project_queryset(self, queryset: QuerySet[Any]) -> QuerySet[Any]:
        """Filter by membership and optional UUID project query parameter."""
        if not is_platform_admin(self.request.user):
            queryset = queryset.filter(project__memberships__user=self.request.user)
        project_id = self.request.query_params.get("project")
        if project_id:
            project_id = serializers.UUIDField().run_validation(project_id)
            queryset = queryset.filter(project_id=project_id)
        return queryset.distinct()


class TestCaseViewSet(_ProjectScopedViewSet):
    """CRUD project-scoped test cases."""

    serializer_class = TestCaseSerializer

    def get_queryset(self) -> QuerySet[TestCase]:
        """Return only project-visible cases in deterministic case order."""
        return self._project_queryset(TestCase.objects.select_related("project").order_by("case_id"))

    def can_write(self, user: Any, project: Any) -> bool:
        """Expose case write capability to the shared object permission."""
        return can_write_test_case(user, project)

    def perform_create(self, serializer: TestCaseSerializer) -> None:
        """Validate create project visibility and write capability before save."""
        project = serializer.validated_data["project"]
        if not can_write_test_case(self.request.user, project):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("当前账号没有创建测试用例的权限。")
        serializer.save()


class TestRunViewSet(_ProjectScopedViewSet):
    """Create, inspect, and execute project test runs."""

    serializer_class = TestRunSerializer

    def get_queryset(self) -> QuerySet[TestRun]:
        """Return runs with their cases and safe results prefetched."""
        return self._project_queryset(
            TestRun.objects.select_related("project", "environment", "created_by")
            .prefetch_related("test_cases", "results__test_case")
        )

    def can_write(self, user: Any, project: Any) -> bool:
        """Allow run creation and edits to project execution-capable members."""
        return can_execute_test(user, project)

    def perform_create(self, serializer: TestRunSerializer) -> None:
        """Gate run creation using the selected project before persisting it."""
        project = serializer.validated_data.get("project")
        if project is None:
            project = serializer.initial_data.get("project_id")
        if not can_execute_test(self.request.user, project):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("当前账号没有创建测试执行的权限。")
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=("post",), url_path="execute")
    def execute(self, request: Request, pk: str | None = None) -> Response:
        """Execute one authorized run and return persisted result metadata."""
        run = self.get_object()
        if not can_execute_test(request.user, run.project):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("当前账号没有执行此项目测试的权限。")
        if run.status == TestRun.Status.RUNNING:
            return Response({"detail": "该测试执行正在进行中，请稍后刷新。"}, status=status.HTTP_409_CONFLICT)
        run = execute_test_run(run)
        return Response(self.get_serializer(run).data)

    @action(detail=True, methods=("get",), url_path="results")
    def results(self, request: Request, pk: str | None = None) -> Response:
        """Return safe result records for one visible run."""
        run = self.get_object()
        return Response(TestResultSerializer(run.results.select_related("test_case").all()[:500], many=True).data)
