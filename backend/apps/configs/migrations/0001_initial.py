# Generated for task T007.

import django.core.validators
from django.db import migrations, models

import apps.configs.models


class Migration(migrations.Migration):
    """Create the initial model configuration table."""

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ModelConfig",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=100, unique=True, verbose_name="配置名称")),
                (
                    "provider",
                    models.CharField(
                        choices=[
                            ("openai", "OpenAI"),
                            ("anthropic", "Anthropic"),
                            ("google", "Google"),
                            ("qwen", "通义千问"),
                            ("baidu", "文心一言"),
                            ("deepseek", "DeepSeek"),
                            ("zhipu", "智谱"),
                            ("azure", "Azure OpenAI"),
                            ("custom", "OpenAI 兼容"),
                            ("local", "Ollama / vLLM"),
                        ],
                        max_length=20,
                        verbose_name="提供商",
                    ),
                ),
                ("model_name", models.CharField(max_length=100, verbose_name="模型名称")),
                (
                    "model_type",
                    models.CharField(
                        choices=[
                            ("chat", "对话"),
                            ("embedding", "向量"),
                            ("vision", "视觉"),
                        ],
                        db_index=True,
                        default="chat",
                        max_length=20,
                        verbose_name="模型类型",
                    ),
                ),
                (
                    "api_key_encrypted",
                    models.TextField(blank=True, default="", verbose_name="加密 API Key"),
                ),
                (
                    "api_base_url",
                    models.URLField(blank=True, max_length=500, verbose_name="API 基础地址"),
                ),
                (
                    "parameters",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        validators=[apps.configs.models.validate_parameters_object],
                        verbose_name="模型参数",
                    ),
                ),
                ("is_default", models.BooleanField(db_index=True, default=False, verbose_name="默认模型")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="启用")),
                (
                    "priority",
                    models.PositiveIntegerField(
                        db_index=True,
                        default=100,
                        validators=[django.core.validators.MinValueValidator(0)],
                        verbose_name="优先级",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
            ],
            options={
                "verbose_name": "模型配置",
                "verbose_name_plural": "模型配置",
                "ordering": ("priority", "name"),
                "indexes": [
                    models.Index(
                        fields=["model_type", "is_active", "priority"],
                        name="config_model_route_idx",
                    )
                ],
            },
        )
    ]
