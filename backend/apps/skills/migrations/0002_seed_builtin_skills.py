from django.db import migrations


def seed_builtin_skills(apps, schema_editor):
    Skill = apps.get_model("skills", "Skill")
    definitions = {
        "接口测试": "根据接口定义生成请求、响应和断言检查计划。",
        "AI测试": "根据评测目标生成 AI 输出质量检查维度。",
        "用例生成": "从需求和风险信息整理测试用例生成计划。",
    }
    for name, description in definitions.items():
        Skill.objects.get_or_create(name=name, version="1.0.0", project=None, defaults={"description": description, "category": "core", "triggers": {"explicit": [name]}, "capabilities": [], "tools": [], "knowledge": [], "input_schema": {}, "output_schema": {}})


def remove_builtin_skills(apps, schema_editor):
    Skill = apps.get_model("skills", "Skill")
    Skill.objects.filter(project=None, name__in=["接口测试", "AI测试", "用例生成"], version="1.0.0").delete()


class Migration(migrations.Migration):
    dependencies = [("skills", "0001_initial")]
    operations = [migrations.RunPython(seed_builtin_skills, remove_builtin_skills)]
