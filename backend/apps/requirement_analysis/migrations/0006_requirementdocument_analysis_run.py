from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("requirement_analysis", "0005_requirementanalysis_quality_and_baseline"),
        ("skills", "0014_skillchainrun_skillchainnoderun_skillchainrunevent_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="requirementdocument",
            name="analysis_run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="requirement_analysis_documents",
                to="skills.skillchainrun",
                verbose_name="需求分析父运行",
            ),
        ),
    ]
