"""Persistent Skill definitions and trigger contracts."""
from typing import Any
from uuid import uuid4
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

def validate_object(value: Any) -> None:
    """Require a JSON object."""
    if not isinstance(value, dict): raise ValidationError("技能配置必须是 JSON 对象。")

def validate_string_list(value: Any) -> None:
    """Require unique non-empty strings."""
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value): raise ValidationError("技能列表必须是非空字符串数组。")
    if len(value) != len(set(value)): raise ValidationError("技能列表不能包含重复项。")

class Skill(models.Model):
    """A versioned global or project-scoped Skill definition."""
    class Category(models.TextChoices):
        CORE = "core", "核心"; SPECIALIZED = "specialized", "专业"; AUXILIARY = "auxiliary", "辅助"; CUSTOM = "custom", "自定义"
    class Status(models.TextChoices):
        ENABLED = "enabled", "启用"; DISABLED = "disabled", "停用"
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="skills", verbose_name="项目")
    name = models.CharField("技能名称", max_length=100)
    version = models.CharField("版本", max_length=30, default="1.0.0")
    description = models.TextField("描述", blank=True)
    category = models.CharField("分类", max_length=20, choices=Category.choices, default=Category.CORE, db_index=True)
    triggers = models.JSONField("触发条件", default=dict, validators=[validate_object])
    capabilities = models.JSONField("能力列表", default=list, validators=[validate_string_list])
    tools = models.JSONField("所需工具", default=list, validators=[validate_string_list])
    knowledge = models.JSONField("所需知识", default=list, validators=[validate_string_list])
    input_schema = models.JSONField("输入定义", default=dict, validators=[validate_object])
    output_schema = models.JSONField("输出定义", default=dict, validators=[validate_object])
    runtime_key = models.CharField("运行时绑定", max_length=100, default="configured", blank=True)
    timeout_seconds = models.PositiveIntegerField("超时秒数", default=30)
    status = models.CharField("状态", max_length=20, choices=Status.choices, default=Status.ENABLED, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_skills", verbose_name="创建者")
    created_at = models.DateTimeField("创建时间", auto_now_add=True); updated_at = models.DateTimeField("更新时间", auto_now=True)
    class Meta:
        verbose_name = "技能"; verbose_name_plural = "技能"; ordering = ("name", "version")
        constraints = [models.UniqueConstraint(fields=("project", "name", "version"), name="skills_scope_name_version_uniq")]
    def __str__(self) -> str: return f"{self.name} v{self.version}"
    def clean(self) -> None:
        """Enforce custom Skill project scope and JSON shapes."""
        super().clean()
        if self.category == self.Category.CUSTOM and self.project_id is None: raise ValidationError({"project": "自定义技能必须关联项目。"})
        if self.category != self.Category.CUSTOM and self.project_id is not None: raise ValidationError({"project": "内置技能不能绑定项目。"})
        for field in ("triggers", "input_schema", "output_schema"): validate_object(getattr(self, field))
        for field in ("capabilities", "tools", "knowledge"): validate_string_list(getattr(self, field))
