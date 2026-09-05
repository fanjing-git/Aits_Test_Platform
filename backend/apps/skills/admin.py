from django.contrib import admin
from apps.skills.models import Skill

@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    """Expose Skill definitions for controlled administration."""
    list_display = ("name", "version", "category", "project", "status", "updated_at")
    list_filter = ("category", "status", "project")
    search_fields = ("name", "description")
    autocomplete_fields = ("project", "created_by")
