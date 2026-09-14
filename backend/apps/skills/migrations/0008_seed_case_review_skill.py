from django.db import migrations


def seed_case_review(apps, schema_editor):
    """Register the business-facing case review Skill definition."""
    Skill = apps.get_model("skills", "Skill")
    Skill.objects.get_or_create(
        name="用例评审",
        version="1.0.0",
        project=None,
        defaults={
            "description": "检查测试用例的覆盖、风险、边界和可执行性。",
            "category": "core",
            "triggers": {"explicit": ["用例评审", "评审用例"]},
            "capabilities": [],
            "tools": [],
            "knowledge": [],
            "input_schema": {"type": "object", "required": ["cases"]},
            "output_schema": {"type": "object"},
        },
    )


def remove_case_review(apps, schema_editor):
    """Remove only the seed created by this migration on rollback."""
    apps.get_model("skills", "Skill").objects.filter(name="用例评审", version="1.0.0", project=None).delete()


class Migration(migrations.Migration):
    dependencies = [("skills", "0007_seed_requirement_analysis_skill")]
    operations = [migrations.RunPython(seed_case_review, remove_case_review)]
