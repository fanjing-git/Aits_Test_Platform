"""Django application configuration for business linkage records."""

from django.apps import AppConfig


class BusinessLinkageConfig(AppConfig):
    """Register project-scoped business linkage models."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.business_linkage"
    verbose_name = "业务联调"
