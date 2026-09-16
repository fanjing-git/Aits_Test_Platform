"""Django application configuration for test execution records."""

from django.apps import AppConfig


class TestsConfig(AppConfig):
    """Register the project-scoped test execution application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tests"
    verbose_name = "接口测试"
