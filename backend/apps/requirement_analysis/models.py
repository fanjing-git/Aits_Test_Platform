"""Project-scoped requirement documents and structured analysis results."""
from typing import Any
from uuid import uuid4
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

def validate_list(value: Any) -> None:
    """Require a JSON list."""
    if not isinstance(value, list): raise ValidationError("该字段必须是 JSON 数组。")

def validate_object(value: Any) -> None:
    """Require a JSON object."""
    if not isinstance(value, dict): raise ValidationError("该字段必须是 JSON 对象。")

class RequirementDocument(models.Model):
    """A versioned project requirement source."""
    class SourceType(models.TextChoices):
        FILE = "file", "文件"; ONLINE_LINK = "online_link", "在线链接"; SCREENSHOT = "screenshot", "截图"; MANUAL = "manual", "手工录入"
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "已上传"; PARSING = "parsing", "解析中"; ANALYZING = "analyzing", "分析中"; ANALYZED = "analyzed", "已分析"; FAILED = "failed", "失败"
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="requirement_documents", verbose_name="项目")
    title = models.CharField("标题", max_length=500)
    version = models.CharField("版本", max_length=20, default="1.0")
    source_type = models.CharField("来源类型", max_length=20, choices=SourceType.choices, default=SourceType.MANUAL)
    source_url = models.URLField("来源地址", max_length=1000, blank=True)
    file_path = models.CharField("文件路径", max_length=1000, blank=True)
    content_text = models.TextField("正文", blank=True)
    status = models.CharField("状态", max_length=20, choices=Status.choices, default=Status.UPLOADED, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_requirement_documents", verbose_name="创建者")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    def __str__(self) -> str: return f"{self.title} v{self.version}"
    def clean(self) -> None:
        """Validate source-specific fields."""
        super().clean()
        if self.source_type == self.SourceType.ONLINE_LINK and not self.source_url: raise ValidationError({"source_url":"在线链接必须提供来源地址。"})
        if self.source_type == self.SourceType.FILE and not self.file_path and not self.content_text: raise ValidationError({"file_path":"文件来源必须提供文件或正文。"})
        if self.source_type == self.SourceType.MANUAL and not self.content_text.strip(): raise ValidationError({"content_text":"手工录入内容不能为空。"})

class RequirementAnalysis(models.Model):
    """Structured analysis result linked to one requirement document."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    document = models.ForeignKey(RequirementDocument, on_delete=models.CASCADE, related_name="analyses", verbose_name="需求文档")
    modules = models.JSONField("功能模块", default=list, validators=[validate_list])
    functions = models.JSONField("功能点", default=list, validators=[validate_list])
    linkages = models.JSONField("联合功能", default=list, validators=[validate_list])
    test_points = models.JSONField("测试点", default=list, validators=[validate_list])
    coverage_report = models.JSONField("覆盖度报告", default=dict, validators=[validate_object])
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    class Meta:
        verbose_name = "需求分析结果"; verbose_name_plural = "需求分析结果"; ordering = ("-created_at",)
    def __str__(self) -> str: return f"{self.document.title} / 分析结果"
