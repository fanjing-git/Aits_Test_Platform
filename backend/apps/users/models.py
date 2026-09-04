"""Persistence models for user-specific platform settings."""

from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def validate_json_object(value: Any) -> None:
    """Require preference values to use a JSON object at the top level."""
    if not isinstance(value, dict):
        raise ValidationError("偏好设置必须是 JSON 对象。")


class UserProfile(models.Model):
    """Extend Django's user with platform role and personal preferences."""

    class Role(models.TextChoices):
        """Roles supported by the platform permission model."""

        ADMIN = "admin", "管理员"
        TEST_LEADER = "test_leader", "测试负责人"
        TESTER = "tester", "测试工程师"
        DEVELOPER = "developer", "开发工程师"
        VIEWER = "viewer", "访客"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="用户",
    )
    role = models.CharField(
        "角色",
        max_length=20,
        choices=Role.choices,
        default=Role.VIEWER,
        db_index=True,
    )
    preferences = models.JSONField(
        "偏好设置",
        default=dict,
        blank=True,
        validators=[validate_json_object],
    )
    notification_preferences = models.JSONField(
        "通知偏好",
        default=dict,
        blank=True,
        validators=[validate_json_object],
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        """Define stable naming and ordering for administration."""

        verbose_name = "用户资料"
        verbose_name_plural = "用户资料"
        ordering = ("user__username",)

    def __str__(self) -> str:
        """Return a readable profile label for logs and administration."""
        return f"{self.user.get_username()}（{self.get_role_display()}）"
