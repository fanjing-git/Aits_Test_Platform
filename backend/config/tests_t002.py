"""Unit and integration tests for multi-environment and Celery configuration."""

import os
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.settings.utils import get_required_env
from config.tasks import health_probe


class EnvironmentSettingsUnitTests(SimpleTestCase):
    """Verify strict environment-variable handling."""

    def test_required_environment_variable_rejects_empty_value(self) -> None:
        """An empty secret or connection value must fail fast."""
        with patch.dict(os.environ, {"T002_REQUIRED_VALUE": ""}):
            with self.assertRaises(ImproperlyConfigured):
                get_required_env("T002_REQUIRED_VALUE")

    def test_required_environment_variable_returns_configured_value(self) -> None:
        """A configured value should be returned without transformation."""
        with patch.dict(os.environ, {"T002_REQUIRED_VALUE": "configured"}):
            self.assertEqual(get_required_env("T002_REQUIRED_VALUE"), "configured")


class CeleryDevelopmentIntegrationTests(SimpleTestCase):
    """Verify the local eager-mode Celery execution path."""

    def test_health_probe_runs_in_eager_mode(self) -> None:
        """The task should execute locally without a Redis service."""
        result = health_probe.delay()

        self.assertTrue(result.successful())
        self.assertEqual(result.get()["component"], "celery")

