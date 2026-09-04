"""Application configuration for user management."""

from django.apps import AppConfig


class UsersConfig(AppConfig):
    """Configure the user profile application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.users"
    verbose_name = "用户与权限"

    def ready(self) -> None:
        """Register user lifecycle signal handlers."""
        from apps.users import signals  # noqa: F401
