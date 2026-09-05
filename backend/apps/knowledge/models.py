"""Project-aware knowledge bases, source documents, QA and embeddings."""
from typing import Any
from uuid import uuid4
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


def validate_object(value: Any) -> None:
    """Require extensible metadata to be a JSON object."""
    if not isinstance(value, dict):
        raise ValidationError("知识元数据必须是 JSON 对象。")


def validate_vector(value: Any) -> None:
    """Require a finite numeric vector; dimensions are provider-specific."""
    if not isinstance(value, list) or not value:
        raise ValidationError("向量必须是非空 JSON 数组。")
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        raise ValidationError("向量中的每一项都必须是数字。")


class KnowledgeBase(models.Model):
    """A named collection whose project controls access to its assets."""
    class Category(models.TextChoices):
        BUILTIN = "builtin", "内置知识"
        PROJECT = "project", "项目知识"
        EXPERIENCE = "experience", "经验知识"
        SUBJECT = "subject", "被测对象知识"
        REALTIME = "realtime", "实时知识"
        PERSONAL = "personal", "个人知识"

    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        ARCHIVED = "archived", "归档"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="knowledge_bases", verbose_name="项目")
    name = models.CharField("知识库名称", max_length=150)
    description = models.TextField("说明", blank=True)
    category = models.CharField("知识分类", max_length=20, choices=Category.choices, default=Category.PROJECT, db_index=True)
    status = models.CharField("状态", max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_knowledge_bases", verbose_name="创建者")
    metadata = models.JSONField("元数据", default=dict, blank=True, validators=[validate_object])
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "知识库"; verbose_name_plural = "知识库"
        ordering = ("name",)
        constraints = [models.UniqueConstraint(fields=("project", "name"), name="knowledge_project_name_uniq")]
        indexes = [models.Index(fields=("project", "category", "status"), name="knowledge_scope_status_idx")]

    def __str__(self) -> str:
        """Return a readable collection name."""
        return self.name

    def clean(self) -> None:
        """Enforce category scope semantics and JSON shape."""
        super().clean()
        if self.category == self.Category.PROJECT and self.project_id is None:
            raise ValidationError({"project": "项目知识必须关联项目。"})
        if self.category == self.Category.PERSONAL and self.project_id is not None:
            raise ValidationError({"project": "个人知识不能归属项目。"})
        validate_object(self.metadata)


class ReviewStatus(models.TextChoices):
    """Shared human-review lifecycle for knowledge assets."""
    PENDING = "pending", "待审核"
    APPROVED = "approved", "已通过"
    REJECTED = "rejected", "已拒绝"
    PAUSED = "paused", "已暂缓"


class Document(models.Model):
    """A source document awaiting parsing, review and indexing."""
    class SourceType(models.TextChoices):
        FILE = "file", "文件"
        ONLINE_LINK = "online_link", "在线链接"
        MANUAL = "manual", "手动录入"
        API = "api", "API同步"

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "已上传"
        PARSING = "parsing", "解析中"
        READY = "ready", "已解析"
        FAILED = "failed", "解析失败"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    knowledge_base = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="documents", verbose_name="知识库")
    title = models.CharField("标题", max_length=500)
    source_type = models.CharField("来源类型", max_length=20, choices=SourceType.choices, default=SourceType.MANUAL)
    source_url = models.URLField("来源地址", max_length=1000, blank=True)
    file_path = models.CharField("文件路径", max_length=1000, blank=True)
    content_text = models.TextField("正文", blank=True)
    status = models.CharField("解析状态", max_length=20, choices=Status.choices, default=Status.UPLOADED, db_index=True)
    review_status = models.CharField("审核状态", max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.PENDING, db_index=True)
    review_note = models.CharField("审核备注", max_length=500, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_knowledge_documents", verbose_name="审核人")
    reviewed_at = models.DateTimeField("审核时间", null=True, blank=True)
    metadata = models.JSONField("元数据", default=dict, blank=True, validators=[validate_object])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_knowledge_documents", verbose_name="创建者")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "知识文档"; verbose_name_plural = "知识文档"
        ordering = ("knowledge_base__name", "title")
        constraints = [models.CheckConstraint(check=~(models.Q(source_url="") & models.Q(file_path="") & models.Q(content_text="")), name="knowledge_document_source_present")]

    def __str__(self) -> str:
        """Return the document title."""
        return self.title

    def clean(self) -> None:
        """Require a source appropriate to the selected source type."""
        super().clean(); validate_object(self.metadata)
        if self.source_type == self.SourceType.FILE and not self.file_path:
            raise ValidationError({"file_path": "文件来源必须提供文件路径。"})
        if self.source_type == self.SourceType.ONLINE_LINK and not self.source_url:
            raise ValidationError({"source_url": "在线来源必须提供链接。"})
        if self.source_type in {self.SourceType.MANUAL, self.SourceType.API} and not self.content_text.strip():
            raise ValidationError({"content_text": "手动或API来源必须提供正文。"})


class QAPair(models.Model):
    """A question and answer candidate with an explicit review state."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    knowledge_base = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="qa_pairs", verbose_name="知识库")
    question = models.TextField("问题")
    answer = models.TextField("答案")
    review_status = models.CharField("审核状态", max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.PENDING, db_index=True)
    quality_score = models.DecimalField("质量评分", max_digits=5, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(1)])
    source_document = models.ForeignKey(Document, null=True, blank=True, on_delete=models.SET_NULL, related_name="qa_pairs", verbose_name="来源文档")
    metadata = models.JSONField("元数据", default=dict, blank=True, validators=[validate_object])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_knowledge_qa_pairs", verbose_name="创建者")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_knowledge_qa_pairs", verbose_name="审核人")
    reviewed_at = models.DateTimeField("审核时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "知识问答对"; verbose_name_plural = "知识问答对"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        """Return a compact question label."""
        return self.question[:80]

    def clean(self) -> None:
        """Require non-empty content and keep source document in the same base."""
        super().clean(); validate_object(self.metadata)
        if not self.question.strip() or not self.answer.strip():
            raise ValidationError("问题和答案不能为空。")
        if self.source_document_id and self.source_document.knowledge_base_id != self.knowledge_base_id:
            raise ValidationError({"source_document": "来源文档必须属于同一知识库。"})
        if self.review_status == ReviewStatus.APPROVED and not self.reviewed_by_id:
            raise ValidationError({"reviewed_by": "已通过的知识必须记录审核人。"})


class Embedding(models.Model):
    """Store a chunk vector and provenance for later pgvector migration."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    knowledge_base = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="embeddings", verbose_name="知识库")
    document = models.ForeignKey(Document, null=True, blank=True, on_delete=models.CASCADE, related_name="embeddings", verbose_name="文档")
    qa_pair = models.ForeignKey(QAPair, null=True, blank=True, on_delete=models.CASCADE, related_name="embeddings", verbose_name="问答对")
    chunk_index = models.PositiveIntegerField("分块序号", default=0)
    content = models.TextField("分块内容")
    vector = models.JSONField("向量", null=True, blank=True, validators=[validate_vector])
    model_name = models.CharField("向量模型", max_length=150, blank=True)
    metadata = models.JSONField("元数据", default=dict, blank=True, validators=[validate_object])
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "知识向量"; verbose_name_plural = "知识向量"
        ordering = ("knowledge_base__name", "chunk_index")
        constraints = [models.UniqueConstraint(fields=("knowledge_base", "document", "chunk_index"), name="knowledge_document_chunk_uniq")]

    def __str__(self) -> str:
        """Return source and chunk identity."""
        return f"{self.knowledge_base.name} / chunk {self.chunk_index}"

    def clean(self) -> None:
        """Require one source and keep all provenance inside one knowledge base."""
        super().clean(); validate_object(self.metadata)
        if (self.document_id is None) == (self.qa_pair_id is None):
            raise ValidationError("向量必须且只能关联一个文档或问答对。")
        source = self.document or self.qa_pair
        if source.knowledge_base_id != self.knowledge_base_id:
            raise ValidationError({"knowledge_base": "来源必须属于同一知识库。"})
        if self.vector is not None:
            validate_vector(self.vector)
        if not self.content.strip():
            raise ValidationError({"content": "分块内容不能为空。"})
