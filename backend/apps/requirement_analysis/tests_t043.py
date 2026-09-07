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
        self.assertEqual(len(result.linkages), 1)
        self.assertNotIn("sequence", {item["relationship"] for item in result.linkages})
        self.assertTrue(result.coverage_report["data_flow_count"] >= 1)
        self.assertIn("用户", result.coverage_report["actors"])
        self.assertEqual({item["type"] for item in result.test_points}, {"positive", "negative", "boundary"})

    def test_empty_requirement_is_rejected(self) -> None:
        with self.assertRaises(RequirementAnalysisError):
            deep_analyze(" ")

    def test_each_function_gets_forward_reverse_and_boundary_baseline(self) -> None:
        result = deep_analyze("# 登录\n用户提交账号和密码。")
        self.assertEqual(len(result.functions), 1)
        self.assertEqual(len(result.test_points), 7)
        self.assertEqual({item["scenario"] for item in result.test_points}, {"正常流程", "输入校验", "权限拒绝", "依赖失败", "边界值", "重复提交", "状态恢复"})

    def test_unrelated_functions_do_not_become_sequence_linkages(self) -> None:
        result = deep_analyze("# 闂ㄦ埛\n鍚姩娓告垙\n# 璁剧疆\n璋冩暣闊抽噺")
        self.assertEqual(result.linkages, [])

    def test_screenshot_analysis_adds_honest_visual_baseline(self) -> None:
        result = deep_analyze("OCR text", title="背包截图", source_type=RequirementDocument.SourceType.SCREENSHOT)
        self.assertTrue(result.coverage_report["visual_baseline"])
        self.assertEqual(len(result.functions), 5)
        self.assertEqual(len(result.test_points), 35)
        self.assertIn("需人工确认", result.coverage_report["visual_baseline_note"])

    def test_analysis_traces_source_evidence_and_marks_low_confidence(self) -> None:
        result = deep_analyze(
            "乱码 OCR",
            title="截图",
            source_type=RequirementDocument.SourceType.SCREENSHOT,
            evidence=[{"id": "ocr-1", "text": "乱码 OCR", "confidence": 0.2}],
            source_confidence=0.2,
            warnings=["未安装中文 OCR 语言包。"],
        )
        self.assertTrue(result.coverage_report["needs_confirmation"])
        self.assertEqual(result.coverage_report["evidence_count"], 1)
        self.assertEqual(len(result.functions), 4)
        self.assertTrue(all(item["needs_confirmation"] for item in result.test_points))
        self.assertTrue(all("ocr-1" in item["evidence_ids"] for item in result.functions))

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
