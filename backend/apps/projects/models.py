"""Persistence models for projects and their members."""

from typing import Any
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def validate_settings_object(value: Any) -> None:
    """Require project settings to use a JSON object."""
    if not isinstance(value, dict):
        raise ValidationError("项目设置必须是 JSON 对象。")


class Project(models.Model):
    """Top-level isolation boundary for platform testing assets."""

    class Status(models.TextChoices):
        ACTIVE = "active", "进行中"
        PAUSED = "paused", "已暂停"
        ARCHIVED = "archived", "已归档"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    name = models.CharField("项目名称", max_length=100, unique=True)
    description = models.TextField("项目说明", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_projects",
        verbose_name="创建者",
    )
    status = models.CharField(
        "项目状态",
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    settings = models.JSONField(
        "项目设置",
        default=dict,
        blank=True,
        validators=[validate_settings_object],
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "项目"
        verbose_name_plural = "项目"
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class ProjectMember(models.Model):
    """Assign one collaboration role to a user inside a project."""

    class Role(models.TextChoices):
        OWNER = "owner", "所有者"
        MANAGER = "manager", "项目管理员"
        MEMBER = "member", "项目成员"
        VIEWER = "viewer", "只读成员"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name="项目",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="project_memberships",
        verbose_name="用户",
    )
    role = models.CharField(
        "项目角色",
        max_length=20,
        choices=Role.choices,
        default=Role.MEMBER,
        db_index=True,
    )
    joined_at = models.DateTimeField("加入时间", auto_now_add=True)

    class Meta:
        verbose_name = "项目成员"
        verbose_name_plural = "项目成员"
        ordering = ("project__name", "user__username")
        constraints = [
            models.UniqueConstraint(
                fields=("project", "user"),
                name="projects_member_user_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=("project", "role"),
                name="projects_member_role_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.project.name} / {self.user.get_username()}（{self.get_role_display()}）"
