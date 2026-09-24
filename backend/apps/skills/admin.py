from django.contrib import admin
from apps.skills.models import Skill, SkillChain, SkillChainConfiguration, SkillChainGovernanceAudit, SkillChainNodeRun, SkillChainRun, SkillChainRunEvent, SkillInstallation, SkillPermissionAudit

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

    def has_add_permission(self, request) -> bool:
        """Prevent manual records that would bypass the runtime guard."""
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        """Keep audit decisions immutable after they are recorded."""
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        """Retain audit history and disallow destructive admin actions."""
        return False

@admin.register(SkillChain)
class SkillChainAdmin(admin.ModelAdmin):
    """Expose chain contracts and their lifecycle metadata to administrators."""

    list_display = ("name", "version", "project", "status", "updated_at")
    list_filter = ("status", "schema_version")
    search_fields = ("name", "description")


@admin.register(SkillChainConfiguration)
class SkillChainConfigurationAdmin(admin.ModelAdmin):
    """Expose four-layer chain configuration records."""

    list_display = ("chain", "layer", "project", "feature_key", "enabled", "updated_at")
    list_filter = ("layer", "enabled")
    search_fields = ("chain__name", "feature_key", "request_key")
    readonly_fields = ("configuration_snapshot", "created_at", "updated_at")


@admin.register(SkillChainGovernanceAudit)
class SkillChainGovernanceAuditAdmin(admin.ModelAdmin):
    """Expose immutable chain and configuration governance history."""

    list_display = ("action", "object_id", "chain", "configuration", "actor", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("object_id", "reason", "actor__username")
    readonly_fields = (
        "object_id", "action", "before_state", "after_state", "reason",
        "chain", "configuration", "actor", "created_at",
    )

    def has_add_permission(self, request) -> bool:
        """Prevent audit entries from being manufactured in the admin."""
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        """Keep governance events immutable."""
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        """Retain audit history."""
        return False


@admin.register(SkillChainRun)
class SkillChainRunAdmin(admin.ModelAdmin):
    """Expose parent runs and frozen snapshots for operational review."""

    list_display = ("id", "chain", "status", "project", "requested_by", "checkpoint_node_id", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("id", "chain__name", "requested_by__username", "error_code")
    readonly_fields = tuple(field.name for field in SkillChainRun._meta.fields)

    def has_add_permission(self, request) -> bool:
        """Require the runtime service to create authoritative runs."""
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        """Keep run history immutable from manual admin edits."""
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        """Retain parent run evidence."""
        return False


@admin.register(SkillChainNodeRun)
class SkillChainNodeRunAdmin(admin.ModelAdmin):
    """Expose node snapshots and checkpoint state as read-only evidence."""

    list_display = ("run", "position", "node_id", "node_type", "status", "checkpoint_safe", "updated_at")
    list_filter = ("status", "node_type", "checkpoint_safe")
    search_fields = ("node_id", "run__id")
    readonly_fields = tuple(field.name for field in SkillChainNodeRun._meta.fields)

    def has_add_permission(self, request) -> bool:
        """Require the parent runtime to create node records."""
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        """Keep node lineage immutable from admin edits."""
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        """Retain node evidence with its parent run."""
        return False


@admin.register(SkillChainRunEvent)
class SkillChainRunEventAdmin(admin.ModelAdmin):
    """Expose append-only run lineage events without manual mutation."""

    list_display = ("run", "sequence", "event_type", "node_key", "to_status", "created_at")
    list_filter = ("event_type", "to_status", "created_at")
    search_fields = ("run__id", "node_key", "event_type")
    readonly_fields = tuple(field.name for field in SkillChainRunEvent._meta.fields)

    def has_add_permission(self, request) -> bool:
        """Require the runtime service to append events."""
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        """Retain append-only lineage evidence."""
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        """Disallow deleting runtime lineage evidence."""
        return False
