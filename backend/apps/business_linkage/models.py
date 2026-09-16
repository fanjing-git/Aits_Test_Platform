"""Persistence models for project business linkage definitions."""

from typing import Any
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models


def validate_json_array(value: Any) -> None:
    """Require a JSON array for extensible linkage collections."""
    if not isinstance(value, list):
        raise ValidationError("业务联调集合必须是 JSON 数组。")


def validate_identifier_array(value: Any) -> None:
    """Require a unique array of non-empty string test-case identifiers."""
    validate_json_array(value)
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError("关联用例标识必须是非空字符串。")
    if len(value) != len(set(value)):
        raise ValidationError("关联用例标识不能重复。")


class BusinessLinkage(models.Model):
    """Store one project-scoped business workflow and its references."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="business_linkages",
        verbose_name="项目",
    )
    name = models.CharField("链路名称", max_length=200)
    steps = models.JSONField(
        "链路步骤",
        default=list,
        blank=True,
        validators=[validate_json_array],
    )
    dependencies = models.JSONField(
        "依赖关系",
        default=list,
        blank=True,
        validators=[validate_json_array],
    )
    test_case_ids = models.JSONField(
        "关联用例",
        default=list,
        blank=True,
        validators=[validate_identifier_array],
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "业务链路"
        verbose_name_plural = "业务链路"
        ordering = ("project__name", "name", "-created_at")
        indexes = [
            models.Index(
                fields=("project", "name"),
                name="biz_linkage_proj_name_idx",
            )
        ]

    def __str__(self) -> str:
        """Return a readable project-scoped linkage label."""
        return f"{self.project.name} / {self.name}"

    def clean(self) -> None:
        """Validate linkage collection shapes before persistence or API use."""
        super().clean()
        errors: dict[str, list[str]] = {}
        for field_name, validator in (
            ("steps", validate_json_array),
            ("dependencies", validate_json_array),
            ("test_case_ids", validate_identifier_array),
        ):
            try:
                validator(getattr(self, field_name))
            except ValidationError as exc:
                errors[field_name] = exc.messages
        if errors:
            raise ValidationError(errors)
