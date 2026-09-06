import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("skills", "0005_skillinstallation"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SkillPermissionAudit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("permission", models.CharField(max_length=40, verbose_name="Permission")),
                ("allowed", models.BooleanField(default=False)),
                ("reason", models.CharField(max_length=200, verbose_name="Decision reason")),
                ("context_keys", models.JSONField(blank=True, default=list, verbose_name="Context keys")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="skill_permission_audits", to=settings.AUTH_USER_MODEL)),
                ("installation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="permission_audits", to="skills.skillinstallation")),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [models.Index(fields=["installation", "permission", "created_at"], name="skills_perm_audit_idx")],
            },
        ),
    ]
