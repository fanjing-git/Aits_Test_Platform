"""Add immutable blueprint lifecycle timestamps and actor audit snapshots."""

from django.db import migrations, models


def backfill_legacy_publication_time(apps, schema_editor):
    """Treat pre-lifecycle enabled/disabled versions as historically published."""
    SkillChain = apps.get_model("skills", "SkillChain")
    SkillChain.objects.filter(
        status__in=("enabled", "disabled"),
        published_at__isnull=True,
    ).update(published_at=models.F("created_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("skills", "0012_skillchaingovernanceaudit"),
    ]

    operations = [
        migrations.AddField(
            model_name="skillchain",
            name="published_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="发布时间"),
        ),
        migrations.AlterField(
            model_name="skillchain",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "草稿"),
                    ("verified", "已校验"),
                    ("published", "已发布"),
                    ("enabled", "启用"),
                    ("paused", "已暂停"),
                    ("archived", "已归档"),
                    ("disabled", "停用"),
                    ("rolled_back", "已回滚"),
                ],
                db_index=True,
                default="draft",
                max_length=20,
                verbose_name="状态",
            ),
        ),
        migrations.AddField(
            model_name="skillchaingovernanceaudit",
            name="actor_display_name",
            field=models.CharField(blank=True, max_length=150, verbose_name="操作人显示名快照"),
        ),
        migrations.AddField(
            model_name="skillchaingovernanceaudit",
            name="actor_role",
            field=models.CharField(blank=True, max_length=40, verbose_name="操作人角色快照"),
        ),
        migrations.AddField(
            model_name="skillchaingovernanceaudit",
            name="actor_scope",
            field=models.JSONField(blank=True, default=dict, verbose_name="操作人授权范围快照"),
        ),
        migrations.AddField(
            model_name="skillchaingovernanceaudit",
            name="result",
            field=models.CharField(default="success", max_length=20, verbose_name="操作结果"),
        ),
        migrations.RunPython(backfill_legacy_publication_time, migrations.RunPython.noop),
    ]
