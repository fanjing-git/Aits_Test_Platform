from django.apps import AppConfig


class CaseGenerationConfig(AppConfig):
    """Configure generated case records."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.case_generation"
    verbose_name = "用例生成"
