"""Persistence models for configurable AI model providers."""

from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from core.utils.crypto import SecretDecryptionError, decrypt_secret, encrypt_secret


def validate_parameters_object(value: Any) -> None:
    """Require model parameters to use a JSON object at the top level."""
    if not isinstance(value, dict):
        raise ValidationError("模型参数必须是 JSON 对象。")


def validate_variables_object(value: Any) -> None:
    """Require prompt template variables to use a JSON object."""
    if not isinstance(value, dict):
        raise ValidationError("提示词变量必须是 JSON 对象。")


class ModelConfig(models.Model):
    """Store routing metadata and encrypted credentials for one AI model."""

    class Provider(models.TextChoices):
        """Model providers supported by the target platform architecture."""

        OPENAI = "openai", "OpenAI"
        ANTHROPIC = "anthropic", "Anthropic"
        GOOGLE = "google", "Google"
        QWEN = "qwen", "通义千问"
        BAIDU = "baidu", "文心一言"
        DEEPSEEK = "deepseek", "DeepSeek"
        ZHIPU = "zhipu", "智谱"
        AZURE = "azure", "Azure OpenAI"
        CUSTOM = "custom", "OpenAI 兼容"
        LOCAL = "local", "Ollama / vLLM"

    class ModelType(models.TextChoices):
        """Capabilities used later by the model routing layer."""

        CHAT = "chat", "对话"
        EMBEDDING = "embedding", "向量"
        VISION = "vision", "视觉"

    name = models.CharField("配置名称", max_length=100, unique=True)
    provider = models.CharField("提供商", max_length=20, choices=Provider.choices)
    model_name = models.CharField("模型名称", max_length=100)
    model_type = models.CharField(
        "模型类型",
        max_length=20,
        choices=ModelType.choices,
        default=ModelType.CHAT,
        db_index=True,
    )
    api_key_encrypted = models.TextField("加密 API Key", blank=True, default="")
    api_base_url = models.URLField("API 基础地址", max_length=500, blank=True)
    parameters = models.JSONField(
        "模型参数",
        default=dict,
        blank=True,
        validators=[validate_parameters_object],
    )
    is_default = models.BooleanField("默认模型", default=False, db_index=True)
    is_active = models.BooleanField("启用", default=True, db_index=True)
    priority = models.PositiveIntegerField(
        "优先级",
        default=100,
        validators=[MinValueValidator(0)],
        db_index=True,
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        """Define stable ordering and common model-routing indexes."""

        verbose_name = "模型配置"
        verbose_name_plural = "模型配置"
        ordering = ("priority", "name")
        indexes = [
            models.Index(
                fields=("model_type", "is_active", "priority"),
                name="config_model_route_idx",
            )
        ]

    def __str__(self) -> str:
        """Return a readable provider and model label."""
        return f"{self.name}（{self.provider}/{self.model_name}）"

    def set_api_key(self, api_key: str) -> None:
        """Encrypt an API key before assigning it to the persistence field."""
        self.api_key_encrypted = encrypt_secret(api_key)

    def get_api_key(self) -> str:
        """Decrypt the stored API key without exposing it in representations."""
        return decrypt_secret(self.api_key_encrypted)

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Reject non-empty credential values that are not valid Fernet tokens."""
        if self.api_key_encrypted:
            try:
                decrypt_secret(self.api_key_encrypted)
            except SecretDecryptionError as exc:
                raise ValidationError(
                    {"api_key_encrypted": "API Key must be encrypted before storage."}
                ) from exc
        super().save(*args, **kwargs)


class ModelUsageRecord(models.Model):
    """Persist token and cost totals reported by one completed model call."""

    model_config = models.ForeignKey(
        ModelConfig,
        on_delete=models.CASCADE,
        related_name="usage_records",
        verbose_name="模型配置",
    )
    input_tokens = models.PositiveBigIntegerField("输入 Token", default=0)
    output_tokens = models.PositiveBigIntegerField("输出 Token", default=0)
    cost = models.DecimalField("费用", max_digits=18, decimal_places=8, default=0)
    success = models.BooleanField("调用成功", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "模型用量记录"
        verbose_name_plural = "模型用量记录"
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(
                fields=("model_config", "created_at"),
                name="config_usage_model_time_idx",
            )
        ]

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class PromptConfig(models.Model):
    """Store one versioned prompt at a level in the four-tier hierarchy."""

    class Scope(models.TextChoices):
        GLOBAL = "global", "全局默认"
        PROJECT = "project", "项目级"
        SCENE = "scene", "场景级"
        INSTANT = "instant", "即时指定"

    class SceneType(models.TextChoices):
        DEFAULT = "default", "全局默认"
        REQUIREMENT_ANALYSIS = "requirement_analysis", "需求分析"
        CASE_GEN = "case_gen", "用例生成"
        CASE_REVIEW = "case_review", "用例评审"
        API_TEST = "api_test", "接口测试"
        AI_TEST = "ai_test", "AI 测试"
        UI_TEST = "ui_test", "UI 测试"
        APP_TEST = "app_test", "APP 测试"
        PERF_TEST = "perf_test", "性能测试"
        SCREENSHOT_ANALYSIS = "screenshot_analysis", "截图识别"
        REPORT_GEN = "report_gen", "报告生成"

    name = models.CharField("配置名称", max_length=100)
    scope = models.CharField(
        "作用域", max_length=20, choices=Scope.choices, db_index=True
    )
    scene_type = models.CharField(
        "场景类型",
        max_length=50,
        choices=SceneType.choices,
        default=SceneType.DEFAULT,
        db_index=True,
    )
    content = models.TextField("提示词内容")
    variables = models.JSONField(
        "模板变量",
        default=dict,
        blank=True,
        validators=[validate_variables_object],
    )
    version = models.PositiveIntegerField(
        "版本", default=1, validators=[MinValueValidator(1)]
    )
    is_active = models.BooleanField("启用", default=True, db_index=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "提示词配置"
        verbose_name_plural = "提示词配置"
        ordering = ("scope", "scene_type", "name", "-version")
        constraints = [
            models.UniqueConstraint(
                fields=("name", "scope", "scene_type", "version"),
                name="config_prompt_version_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=("scope", "scene_type", "is_active"),
                name="config_prompt_lookup_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name}（{self.scope}/{self.scene_type} v{self.version}）"
