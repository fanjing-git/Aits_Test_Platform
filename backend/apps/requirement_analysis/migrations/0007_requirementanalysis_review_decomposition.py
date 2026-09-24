from django.db import migrations, models
import apps.requirement_analysis.models


class Migration(migrations.Migration):
    dependencies = [
        ("requirement_analysis", "0006_requirementdocument_analysis_run"),
        ("skills", "0014_skillchainrun_skillchainnoderun_skillchainrunevent_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="requirementanalysis",
            name="decomposition",
            field=models.JSONField(default=dict, validators=[apps.requirement_analysis.models.validate_object], verbose_name="需求拆解产物"),
        ),
        migrations.AddField(
            model_name="requirementanalysis",
            name="decomposition_fingerprint",
            field=models.CharField(blank=True, db_index=True, default="", max_length=64, verbose_name="需求拆解指纹"),
        ),
        migrations.AddField(
            model_name="requirementanalysis",
            name="decomposition_run",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name="requirement_decomposition_analyses", to="skills.skillchainrun", verbose_name="需求拆解父运行"),
        ),
        migrations.AddField(
            model_name="requirementanalysis",
            name="decomposition_status",
            field=models.CharField(choices=[("pending", "待执行"), ("passed", "已通过"), ("failed", "失败"), ("completed", "已完成")], db_index=True, default="pending", max_length=20, verbose_name="需求拆解状态"),
        ),
        migrations.AddField(
            model_name="requirementanalysis",
            name="review_report",
            field=models.JSONField(default=dict, validators=[apps.requirement_analysis.models.validate_object], verbose_name="需求评审报告"),
        ),
        migrations.AddField(
            model_name="requirementanalysis",
            name="review_run",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name="requirement_review_analyses", to="skills.skillchainrun", verbose_name="需求评审父运行"),
        ),
        migrations.AddField(
            model_name="requirementanalysis",
            name="review_status",
            field=models.CharField(choices=[("pending", "待执行"), ("passed", "已通过"), ("failed", "失败"), ("completed", "已完成")], db_index=True, default="pending", max_length=20, verbose_name="需求评审状态"),
        ),
    ]
