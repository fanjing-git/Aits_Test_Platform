"""Project-scoped testing environments."""
from typing import Any
from uuid import uuid4
from urllib.parse import urlsplit
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from apps.environments.fields import EncryptedObjectField


def validate_environment_url(value: str) -> None:
    """Allow HTTP endpoints without embedding credentials in public URLs."""
    URLValidator(schemes=["http", "https"])(value)
    parsed = urlsplit(value)
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError("请将认证信息填写在认证配置中，不要放入地址。")


class Environment(models.Model):
    """Store one environment type per project with encrypted configuration."""

    class Name(models.TextChoices):
        """Supported deployment stages."""
        DEV = "dev", "开发环境"
        TEST = "test", "测试环境"
        STAGING = "staging", "预发布环境"
        PROD = "prod", "生产环境"

    class Status(models.TextChoices):
        """Operator-controlled availability."""
        AVAILABLE = "available", "可用"
        MAINTENANCE = "maintenance", "维护中"
        UNAVAILABLE = "unavailable", "不可用"

    class HealthStatus(models.TextChoices):
        """Probe outcome independent from operator-controlled availability."""
        UNKNOWN = "unknown", "未检查"
        HEALTHY = "healthy", "健康"
        UNHEALTHY = "unhealthy", "异常"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="environments", verbose_name="项目")
    name = models.CharField("环境类型", max_length=50, choices=Name.choices)
    base_url = models.URLField("接口基础地址", max_length=500, validators=[validate_environment_url])
    description = models.TextField("环境说明", blank=True)
    status = models.CharField("环境状态", max_length=20, choices=Status.choices, default=Status.UNAVAILABLE)
    health_check_url = models.URLField("健康检查地址", max_length=500, blank=True, validators=[validate_environment_url])
    health_status = models.CharField("健康状态", max_length=20, choices=HealthStatus.choices, default=HealthStatus.UNKNOWN)
    database_config = EncryptedObjectField("数据库连接配置", default=dict, blank=True)
    auth_config = EncryptedObjectField("认证配置", default=dict, blank=True)
    variables = EncryptedObjectField("环境变量", default=dict, blank=True)
    health_checked_at = models.DateTimeField("最近检查时间", null=True, blank=True)
    health_message = models.CharField("检查结果", max_length=200, blank=True)
    health_latency_ms = models.PositiveIntegerField("检查耗时", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        """Enforce project boundaries and stable ordering."""
        verbose_name = "测试环境"
        verbose_name_plural = "测试环境"
        ordering = ("project__name", "name")
        constraints = [models.UniqueConstraint(fields=("project", "name"), name="env_project_name_uniq")]
        indexes = [models.Index(fields=("project", "status"), name="env_project_status_idx")]

    def __str__(self) -> str:
        """Return a credential-free label."""
        return f"{self.project.name} / {self.name}"

    def clean(self) -> None:
        """Validate even empty JSON arrays that Django treats as blank."""
        super().clean()
        errors = {}
        for name in ("database_config", "auth_config", "variables"):
            if not isinstance(getattr(self, name), dict):
                errors[name] = "环境配置必须是 JSON 对象。"
        if errors:
            raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate ordinary model writes before persisting configuration."""
        self.full_clean()
        super().save(*args, **kwargs)
