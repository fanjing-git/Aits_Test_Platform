from django.contrib import admin

from apps.case_generation.models import CaseGenerationRecord


@admin.register(CaseGenerationRecord)
class CaseGenerationRecordAdmin(admin.ModelAdmin):
    """Expose generation progress and counts for administrators."""

    list_display = ("document", "project", "rounds", "total_cases", "status", "created_at")
    list_filter = ("status", "rounds")
    search_fields = ("document__title",)
    readonly_fields = ("created_at",)
