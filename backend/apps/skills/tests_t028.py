from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.projects.models import Project
from apps.skills.base import BaseSkill
from apps.skills.models import Skill
from django.contrib.auth import get_user_model

class SkillModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="skill-owner")
        self.project = Project.objects.create(name="Skill project", created_by=self.user)

    def test_global_skill_and_manifest_contract(self):
        skill = Skill.objects.create(name="接口测试", category=Skill.Category.CORE, capabilities=["discover"], tools=[], knowledge=[])
        self.assertEqual(str(skill), "接口测试 v1.0.0")
        class DemoSkill(BaseSkill):
            name = "demo"
            @property
            def description(self): return "demo skill"
            def execute(self, payload): return {"ok": True, **payload}
        self.assertEqual(DemoSkill().manifest()["name"], "demo")

    def test_custom_requires_project_and_builtin_rejects_project(self):
        with self.assertRaises(ValidationError):
            Skill(name="custom", category=Skill.Category.CUSTOM).full_clean()
        with self.assertRaises(ValidationError):
            Skill(name="builtin", project=self.project, category=Skill.Category.CORE).full_clean()

    def test_contract_json_shapes_and_duplicates_are_rejected(self):
        with self.assertRaises(ValidationError):
            Skill(name="bad", capabilities=["x", "x"]).full_clean()
        with self.assertRaises(ValidationError):
            Skill(name="bad", triggers=[]).full_clean()

    def test_versions_are_unique_within_scope(self):
        Skill.objects.create(name="custom", version="1.0.0", category=Skill.Category.CUSTOM, project=self.project)
        duplicate = Skill(name="custom", version="1.0.0", category=Skill.Category.CUSTOM, project=self.project)
        with self.assertRaises(ValidationError): duplicate.full_clean()
