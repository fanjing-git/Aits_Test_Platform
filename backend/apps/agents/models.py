"""Persistence models for project-scoped agent configurations."""

from typing import Any
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


def validate_object(value: Any) -> None:
    """Require extensible agent settings to be a JSON object."""
    if not isinstance(value, dict):
        raise ValidationError("智能体参数必须是 JSON 对象。")


def validate_reference_list(value: Any) -> None:
    """Require a unique list of non-empty string identifiers."""
    if not isinstance(value, list):
        raise ValidationError("关联引用必须是 JSON 数组。")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError("关联引用中的每一项都必须是非空字符串。")
    if len(value) != len(set(value)):
        raise ValidationError("关联引用不能重复。")


class Agent(models.Model):
    """One immutable-version-friendly agent configuration in a project."""

    class AgentType(models.TextChoices):
        GENERAL = "general", "通用智能体"
        REQUIREMENT_ANALYST = "requirement_analyst", "需求分析"
        CASE_GENERATOR = "case_generator", "用例生成"
        TEST_EXECUTOR = "test_executor", "测试执行"
        REVIEWER = "reviewer", "审核评估"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        DISABLED = "disabled", "停用"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="agents",
        verbose_name="项目",
    )
    name = models.CharField("智能体名称", max_length=100)
    description = models.TextField("说明", blank=True)
    agent_type = models.CharField(
        "智能体类型",
        max_length=30,
        choices=AgentType.choices,
        default=AgentType.GENERAL,
        db_index=True,
    )
    model_config = models.ForeignKey(
        "configs.ModelConfig",
        on_delete=models.PROTECT,
        related_name="agents",
        verbose_name="模型配置",
    )
    prompt_config = models.ForeignKey(
        "configs.PromptConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agents",
        verbose_name="提示词配置",
    )
    knowledge_base_ids = models.JSONField(
        "知识库引用",
        default=list,
        blank=True,
        validators=[validate_reference_list],
    )
    skill_ids = models.JSONField(
        "技能引用",
        default=list,
        blank=True,
        validators=[validate_reference_list],
    )
    parameters = models.JSONField(
        "运行参数",
        default=dict,
        blank=True,
        validators=[validate_object],
    )
    version = models.PositiveIntegerField(
        "版本",
        default=1,
        validators=[MinValueValidator(1)],
    )
    status = models.CharField(
        "状态",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_agents",
        verbose_name="创建者",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "智能体"
        verbose_name_plural = "智能体"
        ordering = ("project__name", "name", "-version")
        constraints = [
            models.UniqueConstraint(
                fields=("project", "name", "version"),
                name="agents_project_name_version_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=("project", "status", "agent_type"),
                name="agents_project_status_type_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.project.name} / {self.name} v{self.version}"

    def clean(self) -> None:
        """Enforce JSON shapes even when Django considers a value blank."""
        super().clean()
        errors = {}
        for field_name in ("knowledge_base_ids", "skill_ids"):
            try:
                validate_reference_list(getattr(self, field_name))
            except ValidationError as exc:
                errors[field_name] = exc.messages
        try:
            validate_object(self.parameters)
        except ValidationError as exc:
            errors["parameters"] = exc.messages
        if errors:
            raise ValidationError(errors)
