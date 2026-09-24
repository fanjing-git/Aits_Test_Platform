from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("case_generation", "0003_casegenerationrecord_review_report_and_more"),
        ("skills", "0014_skillchainrun_skillchainnoderun_skillchainrunevent_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="casegenerationrecord",
            name="generation_run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="case_generation_records",
                to="skills.skillchainrun",
                verbose_name="用例生成父运行",
            ),
        ),
        migrations.AddField(
            model_name="casegenerationrecord",
            name="review_run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="case_review_records",
                to="skills.skillchainrun",
                verbose_name="用例评审父运行",
            ),
        ),
    ]
