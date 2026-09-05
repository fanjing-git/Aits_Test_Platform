"""Application configuration for testing environments."""
from django.apps import AppConfig


class EnvironmentsConfig(AppConfig):
    """Register project environment persistence."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.environments"
    verbose_name = "测试环境"
