"""Focused tests for the T056 BaseExecutor contract."""

import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase as DjangoTestCase

from apps.environments.models import Environment
from apps.projects.models import Project
from apps.tests.executor.base import BaseExecutor, ExecutionResult, ExecutorConfigurationError
from apps.tests.models import TestRun


class SampleExecutor(BaseExecutor):
    """Concrete test double proving the abstract executor contract."""

    def execute(self) -> ExecutionResult:
        """Run the sample pytest file in the prepared workspace."""
        return self.run_pytest("test_sample.py")


class BaseExecutorTests(DjangoTestCase):
    """Verify environment gating, workspace isolation, and pytest parsing."""

    def setUp(self) -> None:
        """Create a ready environment and an isolated workspace root."""
        user = get_user_model().objects.create_user(username="t056-owner", password="safe-test-password")
        project = Project.objects.create(name="T056 Project", created_by=user)
        environment = Environment.objects.create(
            project=project,
            name=Environment.Name.TEST,
            base_url="https://test.example.com",
            status=Environment.Status.AVAILABLE,
            health_status=Environment.HealthStatus.HEALTHY,
            auth_config={"token": "not-returned"},
            variables={"secret": "not-returned"},
        )
        self.run = TestRun.objects.create(project=project, environment=environment, name="T056 run")
        self.temp_root = tempfile.TemporaryDirectory(prefix="aits-t056-")
        self.addCleanup(self.temp_root.cleanup)

    def executor(self, timeout_seconds: int = 10) -> SampleExecutor:
        """Build a concrete executor against the test-only temporary root."""
        return SampleExecutor(self.run, workspace_root=self.temp_root.name, timeout_seconds=timeout_seconds)

    def test_environment_context_contains_metadata_but_not_secret_values(self) -> None:
        """Environment awareness must report configuration presence only."""
        executor = self.executor()
        context = executor.ensure_environment_ready()

        self.assertEqual(context["base_url"], "https://test.example.com")
        self.assertTrue(context["auth_configured"])
        self.assertTrue(context["variables_configured"])
        self.assertNotIn("not-returned", str(context))

    def test_environment_gate_rejects_unhealthy_environment(self) -> None:
        """An unhealthy target must be blocked before pytest starts."""
        self.run.environment.health_status = Environment.HealthStatus.UNHEALTHY
        self.run.environment.save(update_fields=["health_status"])

        with self.assertRaises(ExecutorConfigurationError) as context:
            self.executor().ensure_environment_ready()
        self.assertEqual(context.exception.code, "environment_unhealthy")

    def test_workspace_is_scoped_and_rejects_traversal(self) -> None:
        """Workspace paths cannot escape the project/run directory."""
        executor = self.executor()
        workspace = executor.prepare_workspace()
        self.assertTrue(workspace.is_dir())
        self.assertEqual(workspace.parent.name, str(self.run.project_id))

        with self.assertRaises(ExecutorConfigurationError) as context:
            executor.resolve_workspace_path("../outside.py")
        self.assertEqual(context.exception.code, "workspace_escape")

    def test_pytest_execution_and_result_parsing(self) -> None:
        """A subclass can run pytest and receive unified counts."""
        executor = self.executor()
        executor.write_workspace_file("test_sample.py", "def test_ok():\n    assert 2 + 2 == 4\n")

        result = executor.execute()

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.passed, 1)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.environment["status"], Environment.Status.AVAILABLE)

    def test_pytest_timeout_degrades_to_safe_error(self) -> None:
        """A hung pytest process must return a bounded error result."""
        executor = self.executor(timeout_seconds=1)
        executor.write_workspace_file(
            "test_timeout.py",
            "import time\n\ndef test_slow():\n    time.sleep(2)\n",
        )

        result = executor.run_pytest("test_timeout.py", timeout_seconds=1)

        self.assertEqual(result.status, "error")
        self.assertTrue(result.timed_out)
        self.assertEqual(result.error_code, "pytest_timeout")

    def test_invalid_pytest_file_is_rejected_before_process_start(self) -> None:
        """Missing files must produce an actionable configuration error."""
        with self.assertRaises(ExecutorConfigurationError) as context:
            self.executor().run_pytest(Path("missing.py"))
        self.assertEqual(context.exception.code, "pytest_file_not_found")

    def test_base_executor_remains_abstract(self) -> None:
        """Concrete executors must explicitly implement execute()."""
        with self.assertRaises(TypeError):
            BaseExecutor(self.run, workspace_root=self.temp_root.name)  # type: ignore[abstract]
