"""Application configuration for knowledge assets."""
from django.apps import AppConfig

class KnowledgeConfig(AppConfig):
    """Register project and platform knowledge models."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.knowledge"
    verbose_name = "知识库"
