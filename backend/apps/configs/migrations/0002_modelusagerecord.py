# Generated for task T010.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("configs", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="ModelUsageRecord",
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
                ("input_tokens", models.PositiveBigIntegerField(default=0, verbose_name="输入 Token")),
                ("output_tokens", models.PositiveBigIntegerField(default=0, verbose_name="输出 Token")),
                ("cost", models.DecimalField(decimal_places=8, default=0, max_digits=18, verbose_name="费用")),
                ("success", models.BooleanField(default=True, verbose_name="调用成功")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="创建时间")),
                (
                    "model_config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="usage_records",
                        to="configs.modelconfig",
                        verbose_name="模型配置",
                    ),
                ),
            ],
            options={
                "verbose_name": "模型用量记录",
                "verbose_name_plural": "模型用量记录",
                "ordering": ("-created_at", "-pk"),
                "indexes": [
                    models.Index(
                        fields=["model_config", "created_at"],
                        name="config_usage_model_time_idx",
                    )
                ],
            },
        )
    ]
