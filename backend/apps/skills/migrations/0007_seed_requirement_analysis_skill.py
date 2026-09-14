from django.db import migrations


def seed_requirement_analysis(apps, schema_editor):
    """Register the business-facing requirement analysis Skill definition."""
    Skill = apps.get_model("skills", "Skill")
    Skill.objects.get_or_create(
        name="需求分析",
        version="1.0.0",
        project=None,
        defaults={
            "description": "整理需求上下文，识别功能、角色、验收条件和风险。",
            "category": "core",
            "triggers": {"explicit": ["需求分析", "分析需求"]},
            "capabilities": [],
            "tools": [],
            "knowledge": [],
            "input_schema": {"type": "object", "required": ["requirement"]},
            "output_schema": {"type": "object"},
        },
    )


def remove_requirement_analysis(apps, schema_editor):
    """Remove only the seed created by this migration on rollback."""
    apps.get_model("skills", "Skill").objects.filter(name="需求分析", version="1.0.0", project=None).delete()


class Migration(migrations.Migration):
    dependencies = [("skills", "0006_skillpermissionaudit")]
    operations = [migrations.RunPython(seed_requirement_analysis, remove_requirement_analysis)]
