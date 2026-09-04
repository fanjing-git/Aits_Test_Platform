"""Django Admin fallback for platform administrators."""

from django.contrib import admin

from apps.configs.models import ModelConfig, ModelUsageRecord, PromptConfig


@admin.register(ModelConfig)
class ModelConfigAdmin(admin.ModelAdmin):
    """Expose safe configuration metadata; encrypted credentials stay hidden."""

    list_display = (
        "name",
        "provider",
        "model_name",
        "model_type",
        "is_active",
        "is_default",
        "priority",
        "updated_at",
    )
    list_filter = ("provider", "model_type", "is_active", "is_default")
    search_fields = ("name", "model_name")
    exclude = ("api_key_encrypted",)


@admin.register(ModelUsageRecord)
class ModelUsageRecordAdmin(admin.ModelAdmin):
    """Keep usage records inspectable without allowing accidental edits."""

    list_display = (
        "model_config",
        "input_tokens",
        "output_tokens",
        "cost",
        "success",
        "created_at",
    )
    list_filter = ("success", "model_config__provider")
    readonly_fields = tuple(field.name for field in ModelUsageRecord._meta.fields)


@admin.register(PromptConfig)
class PromptConfigAdmin(admin.ModelAdmin):
    """Expose versioned prompt configurations to platform administrators."""

    list_display = (
        "name",
        "scope",
        "scene_type",
        "version",
        "is_active",
        "updated_at",
    )
    list_filter = ("scope", "scene_type", "is_active")
    search_fields = ("name", "content")
