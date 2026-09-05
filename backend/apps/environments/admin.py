"""Internal environment metadata inspection without credential display."""
from django.contrib import admin
from apps.environments.models import Environment


@admin.register(Environment)
class EnvironmentAdmin(admin.ModelAdmin):
    """Keep encrypted configuration out of the internal administration form."""
    list_display = ("project", "name", "status", "health_status", "updated_at")
    list_filter = ("name", "status", "health_status")
    search_fields = ("project__name", "description")
    autocomplete_fields = ("project",)
    exclude = ("database_config", "auth_config", "variables")
    readonly_fields = ("health_status", "health_checked_at", "health_message", "health_latency_ms", "created_at", "updated_at")
