"""Django Admin integration for agent configurations."""

from django.contrib import admin

from apps.agents.models import Agent


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "project",
        "agent_type",
        "version",
        "status",
        "model_config",
        "updated_at",
    )
    list_filter = ("status", "agent_type", "project")
    search_fields = ("name", "description", "project__name")
    autocomplete_fields = (
        "project",
        "model_config",
        "prompt_config",
        "created_by",
    )
    readonly_fields = ("created_at", "updated_at")
