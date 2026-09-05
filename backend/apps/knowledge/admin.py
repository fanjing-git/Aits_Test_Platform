"""Admin registrations for knowledge models."""
from django.contrib import admin
from apps.knowledge.models import Document, Embedding, KnowledgeBase, QAPair

@admin.register(KnowledgeBase)
class KnowledgeBaseAdmin(admin.ModelAdmin):
    """List scoped collections and review-safe metadata."""
    list_display = ("name", "project", "category", "status", "created_by", "updated_at")
    list_filter = ("category", "status")
    search_fields = ("name", "description")
    autocomplete_fields = ("project", "created_by")

@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    """Manage source metadata without changing parsing workflows."""
    list_display = ("title", "knowledge_base", "source_type", "status", "created_at")
    list_filter = ("source_type", "status")
    search_fields = ("title", "content_text")
    autocomplete_fields = ("knowledge_base", "created_by")

@admin.register(QAPair)
class QAPairAdmin(admin.ModelAdmin):
    """Expose review state and provenance to authorized administrators."""
    list_display = ("question", "knowledge_base", "review_status", "quality_score", "reviewed_by")
    list_filter = ("review_status",)
    search_fields = ("question", "answer")
    autocomplete_fields = ("knowledge_base", "source_document", "created_by", "reviewed_by")

@admin.register(Embedding)
class EmbeddingAdmin(admin.ModelAdmin):
    """Show provenance while keeping vector payload read-only in admin."""
    list_display = ("knowledge_base", "document", "qa_pair", "chunk_index", "model_name")
    list_filter = ("model_name",)
    search_fields = ("content",)
    autocomplete_fields = ("knowledge_base", "document", "qa_pair")
    readonly_fields = ("vector",)
