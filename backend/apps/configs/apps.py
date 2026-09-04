"""Application configuration for model and prompt settings."""

from django.apps import AppConfig


class ConfigsConfig(AppConfig):
    """Register the platform configuration application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.configs"
    verbose_name = "平台配置"
