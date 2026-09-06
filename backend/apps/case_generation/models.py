"""Persistence models for multi-round test case generation."""
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models


class CaseGenerationRecord(models.Model):
    """Track one project-scoped case generation run and its review counts."""

    class Status(models.TextChoices):
        GENERATING = "generating", "生成中"
        REVIEWING = "reviewing", "评审中"
        COMPLETED = "completed", "已完成"
        FAILED = "failed", "失败"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="case_generation_records")
    document = models.ForeignKey("requirement_analysis.RequirementDocument", on_delete=models.CASCADE, related_name="case_generation_records")
    rounds = models.PositiveSmallIntegerField(default=0)
    total_cases = models.PositiveIntegerField(default=0)
    auto_cases = models.PositiveIntegerField(default=0)
    manual_cases = models.PositiveIntegerField(default=0)
    cases = models.JSONField(default=list)
    coverage_report = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.GENERATING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Order newest generation runs first."""

        ordering = ("-created_at",)
        indexes = [models.Index(fields=("project", "status"), name="case_gen_project_status_idx")]

    def __str__(self) -> str:
        """Return a concise generation record label."""
        return f"{self.document.title} ({self.status})"

    def clean(self) -> None:
        """Ensure the document belongs to the same project boundary."""
        super().clean()
        if self.document_id and self.project_id and self.document.project_id != self.project_id:
            raise ValidationError({"project": "用例生成记录与需求文档必须属于同一项目。"})
