from django.db import migrations

def seed(apps, schema_editor):
    Skill = apps.get_model("skills", "Skill")
    for name in ("性能测试", "APP测试", "安全测试", "截图识别"):
        Skill.objects.get_or_create(name=name, version="1.0.0", project=None, defaults={"category":"specialized", "description":name, "triggers":{"explicit":[name]}, "capabilities":[], "tools":[], "knowledge":[], "input_schema":{}, "output_schema":{}})

def remove(apps, schema_editor):
    apps.get_model("skills", "Skill").objects.filter(project=None, name__in=("性能测试", "APP测试", "安全测试", "截图识别"), version="1.0.0").delete()

class Migration(migrations.Migration):
    dependencies = [("skills", "0002_seed_builtin_skills")]
    operations = [migrations.RunPython(seed, remove)]
