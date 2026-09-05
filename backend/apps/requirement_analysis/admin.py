from django.contrib import admin
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument

@admin.register(RequirementDocument)
class RequirementDocumentAdmin(admin.ModelAdmin):
    """Admin view for requirement sources."""
    list_display = ("title", "project", "version", "source_type", "status", "created_at")
    list_filter = ("source_type", "status", "project")
    search_fields = ("title", "content_text")
    autocomplete_fields = ("project", "created_by")

@admin.register(RequirementAnalysis)
class RequirementAnalysisAdmin(admin.ModelAdmin):
    """Admin view for analysis results."""
    list_display = ("document", "created_at")
    autocomplete_fields = ("document",)
