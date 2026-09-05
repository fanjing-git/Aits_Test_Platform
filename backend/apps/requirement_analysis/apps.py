from django.apps import AppConfig

class RequirementAnalysisConfig(AppConfig):
    """Configure requirement analysis persistence."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.requirement_analysis"
    verbose_name = "需求分析"
