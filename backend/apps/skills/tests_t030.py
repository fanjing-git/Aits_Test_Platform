from django.test import TestCase
from apps.skills.built_in import BUILT_IN_SKILLS, register_builtin_skills
from apps.skills.manager import SkillManager


class BuiltInSkillTests(TestCase):
    def test_all_first_batch_skills_register_and_execute(self):
        manager = SkillManager(); register_builtin_skills(manager)
        self.assertGreaterEqual(len(BUILT_IN_SKILLS), 7)
        self.assertEqual(manager.load("接口测试").execute({"endpoint": "/health/"})["status"], "planned")
        self.assertEqual(manager.load("AI测试").execute({"prompt": "评估回答"})["criteria"], ["accuracy", "relevance", "safety"])
        self.assertEqual(manager.load("用例生成").execute({"requirement": "用户登录"})["case_types"], ["positive", "negative", "boundary"])

    def test_builtin_input_errors_are_actionable(self):
        manager = SkillManager(); register_builtin_skills(manager)
        with self.assertRaises(ValueError): manager.load("接口测试").execute({})
        with self.assertRaises(ValueError): manager.load("AI测试").execute({"prompt": "x", "criteria": [1]})
        with self.assertRaises(ValueError): manager.load("用例生成").execute({"requirement": ""})
