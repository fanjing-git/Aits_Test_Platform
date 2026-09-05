from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("skills", "0003_seed_second_batch")]
    operations = [
        migrations.AddField(model_name="skill", name="runtime_key", field=models.CharField(default="configured", blank=True, max_length=100, verbose_name="运行时绑定")),
        migrations.AddField(model_name="skill", name="timeout_seconds", field=models.PositiveIntegerField(default=30, verbose_name="超时秒数")),
    ]
