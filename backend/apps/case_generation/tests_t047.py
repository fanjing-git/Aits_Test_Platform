"""Focused tests for five-round generated case review."""
from types import SimpleNamespace
from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.case_generation.generator import generate_document_cases
from apps.case_generation.llm_adapter import CaseReviewModelAdapter, _localize_review_text
from apps.case_generation.models import CaseGenerationRecord
from apps.case_generation.reviewer import CaseReviewError, review_cases, review_generation_record
from apps.requirement_analysis.llm_adapter import ModelAnalysisError
from apps.projects.models import Project
from apps.requirement_analysis.analyzer import analyze_requirement_document
from apps.requirement_analysis.models import RequirementDocument


class CaseReviewModelAdapterTests(SimpleTestCase):
    """Verify structured review output is scoped to known cases."""

    def test_structured_review_is_validated(self) -> None:
        runtime = Mock()
        runtime.generate_structured.return_value = {
            "issues": [{"id": "issue-1", "case_id": "case-1", "severity": "medium", "description": "Test case steps are generic and lack specific actions and data.", "suggestion": "Detail the steps with concrete actions, inputs, and expected outcomes.", "evidence_ids": []}],
            "corrections": [{"case_id": "case-1", "field": "steps", "value": ["执行边界值"]}],
            "approved": False,
            "summary": "需要补充边界覆盖",
        }
        manager = Mock()
        manager.execute_with_fallback.side_effect = lambda _task, operation, **_kwargs: operation(runtime, SimpleNamespace(name="fake"))
        prompts = Mock(); prompts.resolve.return_value = SimpleNamespace(content="JSON")
        record = SimpleNamespace(
            cases=[{"id": "case-1", "title": "登录", "steps": ["执行登录"], "expected_result": "成功"}],
            document=SimpleNamespace(content_text="用户登录", parse_evidence=[]),
            project=SimpleNamespace(name="项目"),
        )
        result = CaseReviewModelAdapter(model_manager=manager, prompt_manager=prompts).review(record=record)
        self.assertFalse(result["approved"])
        self.assertEqual(result["issues"][0]["case_id"], "case-1")
        self.assertEqual(result["issues"][0]["description"], "测试步骤过于笼统，缺少具体操作和测试数据。")
        self.assertEqual(result["issues"][0]["suggestion"], "请根据需求补充可执行的操作、输入和预期结果。")
        self.assertIn("Test case steps", result["issues"][0]["model_description"])
        self.assertEqual(_localize_review_text("Unexpected model output"), "请结合需求证据核对模型指出的问题。")

    def test_unknown_case_reference_is_rejected(self) -> None:
        runtime = Mock()
        runtime.generate_structured.return_value = {"issues": [{"case_id": "unknown", "severity": "high", "description": "问题", "suggestion": "修正", "evidence_ids": []}], "corrections": [], "approved": False}
        manager = Mock(); manager.execute_with_fallback.side_effect = lambda _task, operation, **_kwargs: operation(runtime, SimpleNamespace(name="fake"))
        prompts = Mock(); prompts.resolve.return_value = SimpleNamespace(content="JSON")
        record = SimpleNamespace(cases=[{"id": "case-1"}], document=SimpleNamespace(content_text="需求", parse_evidence=[]), project=SimpleNamespace(name="项目"))
        with self.assertRaises(ModelAnalysisError):
            CaseReviewModelAdapter(model_manager=manager, prompt_manager=prompts).review(record=record)


class CaseReviewTests(TestCase):
    """Verify review evidence, approval and safe rejection."""

    def setUp(self) -> None:
        user = get_user_model().objects.create_user(username="case-review-owner")
        project = Project.objects.create(name="Case review project", created_by=user)
        document = RequirementDocument.objects.create(project=project, title="Login", content_text="用户可以登录系统。", created_by=user)
        analysis = analyze_requirement_document(document)
        self.record = generate_document_cases(document, analysis)

    def test_review_runs_five_rounds_and_persists_report(self) -> None:
        reviewed = review_generation_record(self.record)
        self.assertEqual(reviewed.review_rounds, 5)
        self.assertTrue(reviewed.review_report["approved"])
        self.assertEqual(reviewed.status, CaseGenerationRecord.Status.COMPLETED)
        self.assertEqual(len(reviewed.review_report["round_trace"]), 5)

    def test_review_rejects_missing_cases(self) -> None:
        self.record.cases = []
        with self.assertRaises(CaseReviewError): review_cases(self.record)

    def test_review_failure_is_retained_for_audit(self) -> None:
        self.record.cases = []
        with self.assertRaises(CaseReviewError): review_generation_record(self.record)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, CaseGenerationRecord.Status.FAILED)

    def test_model_review_is_merged_into_final_report(self) -> None:
        fake = Mock()
        fake.review.return_value = {"issues": [{"id": "model-issue-1", "code": "coverage", "case_id": self.record.cases[0]["id"], "severity": "low", "dimension": "coverage", "description": "建议增加说明", "suggestion": "补充步骤", "evidence_ids": [], "source": "model"}], "corrections": [], "approved": True, "summary": "基本可执行"}
        result = review_cases(self.record, model_adapter=fake)
        self.assertEqual(result.report["analysis_method"], "model_verified")
        self.assertTrue(any(item.get("source") == "model" for item in result.issues))
