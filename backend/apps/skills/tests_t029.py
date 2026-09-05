from django.core.exceptions import ValidationError
from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.projects.models import Project
from apps.skills.base import BaseSkill
from apps.skills.manager import SkillManager
from apps.skills.models import Skill


class DemoSkill(BaseSkill):
    """Test runtime Skill."""
    name = "接口测试"
    version = "1.0.0"
    @property
    def description(self): return "接口测试技能"
    def execute(self, payload): return dict(payload)


class SkillManagerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="manager-owner")
        self.project = Project.objects.create(name="Manager project", created_by=self.user)
        self.skill = Skill.objects.create(name="接口测试", triggers={"explicit": ["接口", "API"]}, capabilities=["assert"])
        self.manager = SkillManager()

    def test_register_rejects_duplicates_and_loads_enabled_runtime(self):
        self.manager.register(DemoSkill)
        with self.assertRaises(ValueError): self.manager.register(DemoSkill)
        self.assertIsInstance(self.manager.load("接口测试"), DemoSkill)

    def test_load_rejects_disabled_or_unregistered_skill(self):
        self.skill.status = Skill.Status.DISABLED; self.skill.save(update_fields=["status"])
        with self.assertRaises(LookupError): self.manager.load("接口测试")
        self.skill.status = Skill.Status.ENABLED; self.skill.save(update_fields=["status"])
        with self.assertRaises(LookupError): self.manager.load("接口测试")

    def test_match_scores_and_orders_explicit_triggers(self):
        Skill.objects.create(name="API测试", triggers={"explicit": ["接口"]}, capabilities=[])
        matches = self.manager.match("请做接口 API 测试")
        self.assertEqual(matches[0].skill.name, "接口测试")
        self.assertEqual(matches[0].score, 2)

    def test_match_is_project_scoped_and_disabled_skills_are_hidden(self):
        Skill.objects.create(name="项目技能", category=Skill.Category.CUSTOM, project=self.project, triggers={"explicit": ["登录"]}, capabilities=[])
        other = Project.objects.create(name="Other", created_by=self.user)
        Skill.objects.create(name="其他技能", category=Skill.Category.CUSTOM, project=other, triggers={"explicit": ["登录"]}, capabilities=[])
        self.assertEqual([item.skill.name for item in self.manager.match("登录", str(self.project.pk))], ["项目技能"])

    def test_recommend_limit_is_validated(self):
        with self.assertRaises(ValueError): self.manager.recommend("接口", limit=0)
        self.assertEqual(len(self.manager.recommend("接口", limit=1)), 1)
