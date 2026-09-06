from django.contrib import admin
from apps.skills.models import Skill, SkillInstallation, SkillPermissionAudit

@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    """Expose Skill definitions for controlled administration."""
    list_display = ("name", "version", "category", "project", "status", "updated_at")
    list_filter = ("category", "status", "project")
    search_fields = ("name", "description")
    autocomplete_fields = ("project", "created_by")


@admin.register(SkillInstallation)
class SkillInstallationAdmin(admin.ModelAdmin):
    """Expose immutable source and lifecycle metadata for audit review."""

    list_display = ("source_type", "source_url", "version", "status", "approved_by", "installed_by", "created_at")
    list_filter = ("source_type", "status")
    search_fields = ("source_url", "version", "commit_hash", "file_hash")
    readonly_fields = ("created_at", "updated_at", "approved_at", "installed_at", "rolled_back_at")


@admin.register(SkillPermissionAudit)
class SkillPermissionAuditAdmin(admin.ModelAdmin):
    """Expose permission decisions without exposing request values."""

    list_display = ("installation", "permission", "allowed", "reason", "actor", "created_at")
    list_filter = ("permission", "allowed")
    search_fields = ("permission", "reason")
    readonly_fields = ("installation", "permission", "allowed", "reason", "context_keys", "actor", "created_at")
