from django.apps import AppConfig

class SkillsConfig(AppConfig):
    """Configure the Skills application."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.skills"
    verbose_name = "技能"
