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


class AccountActionToken(models.Model):
    """Store one-time account activation and password-reset capabilities."""

    class Kind(models.TextChoices):
        """Supported account actions issued by an administrator."""

        INVITATION = "invitation", "账号激活"
        PASSWORD_RESET = "password_reset", "密码重置"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="account_action_tokens",
        verbose_name="目标用户",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_account_action_tokens",
        verbose_name="发起人",
    )
    kind = models.CharField("动作类型", max_length=30, choices=Kind.choices)
    token_hash = models.CharField("令牌摘要", max_length=64, unique=True)
    expires_at = models.DateTimeField("过期时间")
    used_at = models.DateTimeField("使用时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "账号动作令牌"
        verbose_name_plural = "账号动作令牌"
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("user", "kind", "used_at"),
                name="users_action_user_kind_idx",
            ),
            models.Index(fields=("expires_at",), name="users_action_expiry_idx"),
        ]

    def __str__(self) -> str:
        """Return a safe label without exposing the raw token."""
        return f"{self.user.get_username()} / {self.get_kind_display()}"


class AccountAuditEvent(models.Model):
    """Retain non-sensitive evidence for account and authorization changes."""

    class Event(models.TextChoices):
        """Account lifecycle events visible to administrators."""

        INVITED = "invited", "邀请账号"
        INVITATION_RESENT = "invitation_resent", "重发邀请"
        INVITATION_REVOKED = "invitation_revoked", "撤销邀请"
        ACTIVATED = "activated", "激活账号"
        PASSWORD_RESET_ISSUED = "password_reset_issued", "生成密码重置链接"
        PASSWORD_RESET = "password_reset", "完成密码重置"
        ACCOUNT_UPDATED = "account_updated", "更新账号权限"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="account_audit_events",
        verbose_name="操作人",
    )
    target = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="target_account_audit_events",
        verbose_name="目标账号",
    )
    target_username = models.CharField("目标账号快照", max_length=150)
    event = models.CharField("事件", max_length=40, choices=Event.choices, db_index=True)
    metadata = models.JSONField("安全元数据", default=dict, blank=True)
    created_at = models.DateTimeField("发生时间", auto_now_add=True)

    class Meta:
        verbose_name = "账号审计事件"
        verbose_name_plural = "账号审计事件"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("target_username", "created_at"), name="users_audit_target_idx"),
            models.Index(fields=("event", "created_at"), name="users_audit_event_idx"),
        ]

    def __str__(self) -> str:
        """Return an audit label without exposing credentials or tokens."""
        return f"{self.target_username} / {self.get_event_display()}"
