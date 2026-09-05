"""Periodic health sweep and Celery scheduling tests."""
import os
from unittest.mock import patch
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from apps.environments.models import Environment
from apps.environments.tasks import check_all_environment_health
from apps.projects.models import Project
from config.celery_app import app


class EnvironmentHealthTaskTests(TestCase):
    """Verify scheduled sweeps are safe, bounded and failure-isolated."""

    def setUp(self) -> None:
        """Create environments with and without probe addresses."""
        patcher = patch.dict(os.environ, {"MODEL_CONFIG_FERNET_KEY": Fernet.generate_key().decode()})
        patcher.start(); self.addCleanup(patcher.stop)
        user = get_user_model().objects.create_user(username="task-owner")
        self.project = Project.objects.create(name="Task health project", created_by=user)
        self.first = Environment.objects.create(project=self.project, name="dev", base_url="https://health.example.com", health_check_url="https://health.example.com/a")
        self.second = Environment.objects.create(project=self.project, name="test", base_url="https://health.example.com", health_check_url="https://health.example.com/b")
        self.skipped = Environment.objects.create(project=self.project, name="staging", base_url="https://health.example.com")

    def test_sweep_updates_all_targets_and_isolates_errors(self) -> None:
        """One failed target does not prevent another target from completing."""
        calls = []
        def fake_check(environment):
            calls.append(environment.id)
            if environment.pk == self.second.pk: raise TimeoutError("private detail")
            environment.health_status = Environment.HealthStatus.HEALTHY
            environment.health_message = "safe"
            environment.save(update_fields=("health_status", "health_message", "updated_at"))
            return environment
        with patch("apps.environments.tasks.check_environment", side_effect=fake_check):
            result = check_all_environment_health()
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["healthy"], 1)
        self.assertEqual(result["unhealthy"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(set(calls), {self.first.pk, self.second.pk})
        self.first.refresh_from_db(); self.assertEqual(self.first.health_status, "healthy")
        self.assertEqual(result["errors"][0]["message"], "健康检查未完成。")

    def test_empty_sweep_is_successful(self) -> None:
        """A deployment with no configured health URL produces a useful no-op."""
        Environment.objects.update(health_check_url="")
        self.assertEqual(check_all_environment_health(), {"checked": 0, "healthy": 0, "unhealthy": 0, "skipped": 3, "errors": []})

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_celery_delay_runs_task(self) -> None:
        """The configured eager development path executes the real task."""
        with patch("apps.environments.tasks.check_environment", side_effect=lambda env: env):
            result = check_all_environment_health.delay().get()
        self.assertEqual(result["checked"], 2)

    def test_beat_schedule_is_five_minutes_and_task_is_registered(self) -> None:
        """Celery beat points at the stable task name at the required interval."""
        schedule = app.conf.beat_schedule["environments-check-all-health"]
        self.assertEqual(schedule["task"], "environments.check_all_health")
        self.assertEqual(float(schedule["schedule"]), 300.0)
