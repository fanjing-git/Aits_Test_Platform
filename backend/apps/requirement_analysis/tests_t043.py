"""Focused tests for deterministic requirement deep analysis."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.projects.models import Project
from apps.requirement_analysis.analyzer import RequirementAnalysisError, analyze_requirement_document, deep_analyze
from apps.requirement_analysis.models import RequirementDocument


class RequirementDeepAnalysisTests(TestCase):
    """Verify decomposition, relation and persistence contracts."""

    def test_decomposes_modules_functions_relations_and_data_flows(self) -> None:
        result = deep_analyze("""# 用户管理
用户登录后系统展示用户信息。
管理员更新用户状态并同步权限。
# 订单
用户创建订单，系统保存订单ID。
""", title="Account requirements")
        self.assertEqual(len(result.modules), 2)
        self.assertEqual(len(result.functions), 3)
        self.assertEqual(len(result.linkages), 2)
        self.assertTrue(result.coverage_report["data_flow_count"] >= 1)
        self.assertIn("用户", result.coverage_report["actors"])
        self.assertEqual({item["type"] for item in result.test_points}, {"positive", "negative", "boundary"})

    def test_empty_requirement_is_rejected(self) -> None:
        with self.assertRaises(RequirementAnalysisError):
            deep_analyze(" ")

    def test_document_analysis_is_persisted_and_repeated_runs_keep_history(self) -> None:
        user = get_user_model().objects.create_user(username="deep-analysis-owner")
        project = Project.objects.create(name="Deep analysis project", created_by=user)
        document = RequirementDocument.objects.create(project=project, title="Login", content_text="用户可以登录系统。", created_by=user)
        first = analyze_requirement_document(document)
        second = analyze_requirement_document(document)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(document.__class__.Status.ANALYZED, RequirementDocument.objects.get(pk=document.pk).status)
        self.assertEqual(document.analyses.count(), 2)

    def test_document_without_parsed_content_is_rejected_without_result(self) -> None:
        user = get_user_model().objects.create_user(username="empty-analysis-owner")
        project = Project.objects.create(name="Empty analysis project", created_by=user)
        document = RequirementDocument.objects.create(project=project, title="Empty", content_text="", created_by=user)
        with self.assertRaises(RequirementAnalysisError):
            analyze_requirement_document(document)
        self.assertEqual(document.analyses.count(), 0)
