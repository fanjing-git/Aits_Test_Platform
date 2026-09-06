import apps.skills.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("skills", "0004_runtime_binding"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SkillInstallation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source_type", models.CharField(max_length=20, verbose_name="Source type")),
                ("source_url", models.CharField(max_length=500, verbose_name="Source address")),
                ("version", models.CharField(max_length=30, verbose_name="Locked version")),
                ("manifest", models.JSONField(default=dict, validators=[apps.skills.models.validate_object], verbose_name="Normalized manifest")),
                ("commit_hash", models.CharField(blank=True, max_length=128, verbose_name="Commit hash")),
                ("file_hash", models.CharField(blank=True, max_length=128, verbose_name="File hash")),
                ("status", models.CharField(choices=[("pending", "Pending"), ("verified", "Verified"), ("installed", "Installed"), ("failed", "Failed"), ("rolled_back", "Rolled back"), ("uninstalled", "Uninstalled")], db_index=True, default="pending", max_length=20, verbose_name="Installation status")),
                ("error_message", models.TextField(blank=True, verbose_name="Failure reason")),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("installed_at", models.DateTimeField(blank=True, null=True)),
                ("rolled_back_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approved_skill_installations", to=settings.AUTH_USER_MODEL)),
                ("installed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="installed_skill_installations", to=settings.AUTH_USER_MODEL)),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="requested_skill_installations", to=settings.AUTH_USER_MODEL)),
                ("skill", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="installations", to="skills.skill")),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [models.Index(fields=["source_type", "source_url", "version"], name="skills_install_source_idx")],
            },
        ),
    ]
