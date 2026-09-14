"""Focused tests for the T156 generation/review execution contract."""
from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.case_generation.generator import CaseGenerationError, generate_cases, generate_document_cases
from apps.case_generation.llm_adapter import CaseGenerationModelAdapter
from apps.case_generation.models import CaseGenerationRecord
from apps.case_generation.reviewer import CaseReviewError, review_cases, review_generation_record
from apps.configs.models import ModelConfig, ModelRoutingPolicy
from apps.projects.models import Project
from apps.requirement_analysis.analyzer import analyze_requirement_document
from apps.requirement_analysis.llm_adapter import ModelAnalysisError
from apps.requirement_analysis.models import RequirementDocument


def _generation_payload() -> dict:
    """Return a minimal evidence-grounded analysis payload."""
    return {
        "modules": [{"id": "module-1", "name": "账户"}],
        "functions": [{"id": "function-1", "module_id": "module-1", "name": "登录"}],
        "test_points": [{"id": "point-1", "function_id": "function-1", "description": "登录校验"}],
        "linkages": [],
    }


class T156GenerationTests(SimpleTestCase):
    """Verify generation round states and safe downgrade semantics."""

    def _adapter(self, responses):
        adapter = CaseGenerationModelAdapter.__new__(CaseGenerationModelAdapter)
        adapter.adapter = Mock()
        adapter.adapter.run.side_effect = responses
        return adapter

    @staticmethod
    def _model_response(index: int) -> dict:
        return {
            "cases": [{
                "source_function_id": "function-1",
                "type": "positive",
                "title": f"登录场景 {index}",
                "steps": [f"执行登录 {index}"],
                "expected_result": "登录成功",
            }],
            "coverage_report": {
                "model_route": {"available": True, "effective_source": "feature", "model": {"name": "fake"}},
                "structured_generation": {"status": "completed", "segments": []},
            },
        }

    def test_every_model_round_is_recorded_with_actual_route(self):
        adapter = self._adapter([self._model_response(index) for index in range(1, 6)])
        result = generate_cases(_generation_payload(), model_adapter=adapter, document_text="登录需求")
        self.assertEqual(adapter.adapter.run.call_count, 5)
        self.assertEqual(result.coverage_report["analysis_method"], "model_verified")
        self.assertEqual([item["model_status"] for item in result.round_trace], ["completed"] * 5)
        self.assertEqual([item["model_route"]["model"]["name"] for item in result.round_trace], ["fake"] * 5)

    def test_model_failure_round_is_not_omitted_or_marked_verified(self):
        failure = ModelAnalysisError("provider unavailable", code="provider_unavailable")
        adapter = self._adapter([self._model_response(1), failure, self._model_response(3)])
        with self.assertRaises(CaseGenerationError) as context:
            generate_cases(_generation_payload(), model_adapter=adapter, allow_deterministic_baseline=False)
        trace = context.exception.partial_round_trace
        self.assertEqual(len(trace), 2)
        self.assertEqual(trace[-1]["status"], "failed")
        self.assertEqual(trace[-1]["error_code"], "provider_unavailable")

    def test_explicit_deterministic_fallback_has_distinct_method(self):
        failure = ModelAnalysisError("provider unavailable", code="provider_unavailable")
        adapter = self._adapter([self._model_response(1), failure, self._model_response(3), self._model_response(4), self._model_response(5)])
        result = generate_cases(_generation_payload(), model_adapter=adapter, allow_deterministic_baseline=True)
        self.assertEqual(result.coverage_report["analysis_method"], "deterministic_fallback")
        self.assertNotEqual(result.coverage_report["analysis_method"], "model_verified")
        self.assertEqual(result.round_trace[1]["model_status"], "failed")


class T156ReviewTests(TestCase):
    """Verify review round failure persistence and route-aware status."""

    def setUp(self) -> None:
        user = get_user_model().objects.create_user(username="t156-review-owner")
        project = Project.objects.create(name="T156 review project", created_by=user)
        document = RequirementDocument.objects.create(project=project, title="登录", content_text="用户可以登录系统。", created_by=user)
        analysis = analyze_requirement_document(document)
        self.record = generate_document_cases(document, analysis)

    @staticmethod
    def _review_response() -> dict:
        return {"issues": [], "corrections": [], "approved": True, "summary": "通过", "coverage_report": {}}

    def test_review_failure_keeps_failed_round_and_record_status(self):
        model = ModelConfig.objects.create(
            name="t156-review-model",
            provider=ModelConfig.Provider.CUSTOM,
            model_name="fake",
            model_type=ModelConfig.ModelType.CHAT,
        )
        ModelRoutingPolicy.objects.create(feature_key=ModelRoutingPolicy.FeatureKey.CASE_REVIEW, primary_model=model)
        adapter = Mock()
        adapter.review.side_effect = [self._review_response(), ModelAnalysisError("provider unavailable", code="timeout")]
        with self.assertRaises(CaseReviewError) as context:
            review_generation_record(self.record, model_adapter=adapter)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, CaseGenerationRecord.Status.FAILED)
        self.assertEqual(self.record.review_rounds, 2)
        self.assertEqual(self.record.review_report["round_trace"][-1]["status"], "failed")
        self.assertEqual(self.record.review_report["round_trace"][-1]["error_code"], "timeout")

    def test_model_review_success_is_exactly_five_rounds(self):
        adapter = Mock()
        adapter.review.return_value = self._review_response()
        result = review_cases(self.record, model_adapter=adapter)
        self.assertEqual(adapter.review.call_count, 5)
        self.assertEqual(len(result.round_trace), 5)
        self.assertEqual(result.report["analysis_method"], "model_verified")
