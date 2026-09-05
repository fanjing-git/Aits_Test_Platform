from django.test import TestCase
from apps.skills.built_in import BUILT_IN_SKILLS, register_builtin_skills
from apps.skills.manager import SkillManager

class BuiltInSecondBatchTests(TestCase):
    def test_second_batch_skills_register_and_execute(self):
        manager = SkillManager(); register_builtin_skills(manager)
        self.assertEqual(len(BUILT_IN_SKILLS), 7)
        self.assertEqual(manager.load("性能测试").execute({"concurrency": 60000})["engine"], "locust")
        self.assertEqual(manager.load("APP测试").execute({"platform": "android"})["platform"], "android")
        self.assertEqual(manager.load("安全测试").execute({"target": "staging", "authorized": True})["status"], "planned")
        self.assertEqual(manager.load("截图识别").execute({"image": "local.png"})["status"], "planned")

    def test_second_batch_validates_dangerous_or_malformed_inputs(self):
        manager = SkillManager(); register_builtin_skills(manager)
        with self.assertRaises(ValueError): manager.load("性能测试").execute({"concurrency": 0})
        with self.assertRaises(ValueError): manager.load("APP测试").execute({"platform": "windows"})
        with self.assertRaises(PermissionError): manager.load("安全测试").execute({"target": "prod"})
        with self.assertRaises(ValueError): manager.load("截图识别").execute({})
