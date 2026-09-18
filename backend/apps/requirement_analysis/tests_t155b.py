"""Focused T155B tests for analysis completeness and repeat-run comparison."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.configs.models import ModelConfig, ModelRoutingPolicy
from apps.case_generation.generator import CaseGenerationError, generate_document_cases
from apps.projects.models import Project
from apps.requirement_analysis.models import RequirementDocument
from apps.requirement_analysis.stability import analysis_mapping_gaps, assess_quality
from apps.users.models import UserProfile


def _payload(module_count: int) -> dict:
    """Build an evidence-grounded model payload for deterministic tests."""
    modules = [
        {"id": f"module-{index}", "name": f"模块{index}", "evidence_ids": ["evidence-1", "evidence-2"]}
        for index in range(1, module_count + 1)
    ]
    functions = [
        {"id": f"function-{index}", "module_id": f"module-{index}", "name": f"功能点{index}", "evidence_ids": ["evidence-1", "evidence-2"]}
        for index in range(1, module_count + 1)
    ]
    return {
        "modules": modules,
        "functions": functions,
        "linkages": [],
        "test_points": [
            {"id": f"point-{index}", "function_id": f"function-{index}", "type": "positive", "description": f"测试点{index}", "evidence_ids": ["evidence-1", "evidence-2"]}
            for index in range(1, module_count + 1)
        ],
        "coverage_report": {},
    }


def _round_effect(*responses: object) -> list[object]:
    """Repeat each historical response across T155C's five semantic rounds."""
    return [response for response in responses for _ in range(5)]


class RequirementAnalysisQualityTests(SimpleTestCase):
    """Verify completeness is not inferred from valid JSON alone."""

    def test_missing_evidence_reference_requires_review(self) -> None:
        result = assess_quality(
            payload={
                "modules": [{"id": "module-1", "name": "登录", "evidence_ids": ["evidence-1"]}],
                "functions": [], "linkages": [], "test_points": [],
            },
            evidence=[{"id": "evidence-1", "text": "登录"}, {"id": "evidence-2", "text": "订单"}],
            coverage_report={"structured_generation": {"status": "completed"}},
        )

        self.assertEqual(result["quality_status"], "needs_review")
        self.assertEqual(result["evidence_coverage"]["uncovered_evidence_ids"], ["evidence-2"])

    def test_broken_analysis_hierarchy_requires_review(self) -> None:
        result = assess_quality(
            payload={
                "modules": [{"id": "module-1", "name": "登录", "evidence_ids": ["evidence-1"]}],
                "functions": [{"id": "function-1", "name": "登录", "evidence_ids": ["evidence-1"]}],
                "linkages": [],
                "test_points": [{"id": "point-1", "description": "正常登录", "evidence_ids": ["evidence-1"]}],
            },
            evidence=[{"id": "evidence-1", "text": "登录"}],
            coverage_report={"structured_generation": {"status": "completed"}},
        )

        self.assertEqual(result["quality_status"], "needs_review")
        self.assertEqual(result["mapping_gaps"]["functions_without_module"], ["function-1"])
        self.assertEqual(result["mapping_gaps"]["test_points_without_parent"], ["point-1"])

    def test_missing_human_readable_fields_requires_review(self) -> None:
        gaps = analysis_mapping_gaps({
            "modules": [{"id": "module-1", "evidence_ids": ["evidence-1"]}],
            "functions": [{"id": "function-1", "module_id": "module-1", "evidence_ids": ["evidence-1"]}],
            "linkages": [],
            "test_points": [{"id": "point-1", "function_id": "function-1", "type": "positive", "evidence_ids": ["evidence-1"]}],
        })

        self.assertEqual(gaps["modules_without_name"], ["module-1"])
        self.assertEqual(gaps["functions_without_name"], ["function-1"])
        self.assertEqual(gaps["test_points_without_description"], ["point-1"])


class RequirementAnalysisRepeatRunTests(TestCase):
    """Verify repeated and post-clear analyses expose material count changes."""

    def setUp(self) -> None:
        self.client = APIClient()
        user = get_user_model().objects.create_user(username="t155b-owner")
        user.profile.role = UserProfile.Role.TEST_LEADER
        user.profile.save(update_fields=("role",))
        self.client.force_authenticate(user)
        project = Project.objects.create(name="T155B project", created_by=user)
        self.document = RequirementDocument.objects.create(
            project=project,
            title="稳定性需求",
            version="1.0",
            content_text="登录功能与订单查询功能。",
            parse_evidence=[
                {"id": "evidence-1", "text": "登录功能"},
                {"id": "evidence-2", "text": "订单查询功能"},
            ],
            parse_confidence=0.95,
            created_by=user,
        )
        chat = ModelConfig.objects.create(
            name="t155b-chat",
            provider=ModelConfig.Provider.CUSTOM,
            model_name="t155b-chat-model",
            model_type=ModelConfig.ModelType.CHAT,
        )
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.REQUIREMENT_ANALYSIS,
            primary_model=chat,
        )

    def test_material_count_drop_is_not_marked_complete(self) -> None:
        with patch(
            "apps.requirement_analysis.analyzer.RequirementModelAdapter.analyze",
            side_effect=_round_effect(_payload(3), _payload(1)),
        ):
            first = self.client.post(f"/api/requirement-documents/{self.document.pk}/analyze/", format="json")
            second = self.client.post(f"/api/requirement-documents/{self.document.pk}/analyze/", format="json")

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data["latest_analysis"]["quality_status"], "complete")
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        report = second.data["latest_analysis"]["coverage_report"]
        self.assertEqual(second.data["latest_analysis"]["quality_status"], "needs_review")
        self.assertTrue(report["analysis_comparison"]["material_drop"])
        self.assertEqual(report["analysis_comparison"]["baseline_source"], "previous_analysis")
        with self.assertRaises(CaseGenerationError):
            generate_document_cases(self.document)

    def test_zero_segment_failure_persists_trace_and_provider_code(self) -> None:
        from apps.requirement_analysis.llm_adapter import ModelAnalysisError

        trace = [{
            "segment_id": "segment-0001",
            "status": "failed",
            "input_chars": 1234,
            "evidence_count": 32,
            "error_code": "invalid_response",
        }]
        failure = ModelAnalysisError(
            "provider returned invalid JSON",
            code="invalid_response",
            structured_trace=trace,
            partial_payload={
                "coverage_report": {
                    "structured_generation": {
                        "status": "failed",
                        "segment_count": 9,
                        "completed_segments": 0,
                        "segments": trace,
                    }
                }
            },
        )
        with patch(
            "apps.requirement_analysis.analyzer.RequirementModelAdapter.analyze",
            side_effect=[failure],
        ):
            response = self.client.post(f"/api/requirement-documents/{self.document.pk}/analyze/", format="json")

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(response.data["code"], "invalid_response")
        self.assertEqual(response.data["status"], "failed")
        latest = self.document.analyses.order_by("-created_at").first()
        self.assertIsNotNone(latest)
        self.assertEqual(latest.quality_status, "failed")
        self.assertEqual(latest.coverage_report["analysis_method"], "model_failed")
        self.assertEqual(latest.coverage_report["error_code"], "invalid_response")
        self.assertEqual(latest.coverage_report["structured_generation"]["completed_segments"], 0)
        self.assertEqual(latest.coverage_report["structured_generation"]["segments"], trace)

    def test_failed_attempt_is_not_used_as_the_next_comparison_baseline(self) -> None:
        from apps.requirement_analysis.llm_adapter import ModelAnalysisError

        failure = ModelAnalysisError("provider unavailable", code="provider_http_error")
        with patch(
            "apps.requirement_analysis.analyzer.RequirementModelAdapter.analyze",
            side_effect=[_payload(3)] * 5 + [failure] + [_payload(1)] * 5,
        ):
            first = self.client.post(f"/api/requirement-documents/{self.document.pk}/analyze/", format="json")
            failed = self.client.post(f"/api/requirement-documents/{self.document.pk}/analyze/", format="json")
            recovered = self.client.post(f"/api/requirement-documents/{self.document.pk}/analyze/", format="json")

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(failed.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(recovered.status_code, status.HTTP_200_OK)
        comparison = recovered.data["latest_analysis"]["coverage_report"]["analysis_comparison"]
        self.assertEqual(comparison["baseline_source"], "previous_analysis")
        self.assertTrue(comparison["material_drop"])

    def test_clear_keeps_parsed_snapshot_for_direct_retry(self) -> None:
        original_text = self.document.content_text
        original_evidence = list(self.document.parse_evidence)

        with patch(
            "apps.requirement_analysis.analyzer.RequirementModelAdapter.analyze",
            return_value=_payload(2),
        ):
            first = self.client.post(f"/api/requirement-documents/{self.document.pk}/analyze/", format="json")
            self.assertEqual(first.status_code, status.HTTP_200_OK)
            cleared = self.client.post(f"/api/requirement-documents/{self.document.pk}/clear-analysis/", format="json")
            self.assertEqual(cleared.status_code, status.HTTP_200_OK)
            document = RequirementDocument.objects.get(pk=self.document.pk)

        self.assertEqual(document.content_text, original_text)
        self.assertEqual(document.parse_evidence, original_evidence)
        self.assertEqual(document.status, RequirementDocument.Status.UPLOADED)

    def test_clear_preserves_baseline_for_next_comparison(self) -> None:
        with patch(
            "apps.requirement_analysis.analyzer.RequirementModelAdapter.analyze",
            side_effect=_round_effect(_payload(3), _payload(1)),
        ):
            first = self.client.post(f"/api/requirement-documents/{self.document.pk}/analyze/", format="json")
            self.assertEqual(first.status_code, status.HTTP_200_OK)
            cleared = self.client.post(f"/api/requirement-documents/{self.document.pk}/clear-analysis/", format="json")
            second = self.client.post(f"/api/requirement-documents/{self.document.pk}/analyze/", format="json")

        self.assertEqual(cleared.status_code, status.HTTP_200_OK)
        self.assertTrue(cleared.data["analysis_baseline_preserved"])
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        report = second.data["latest_analysis"]["coverage_report"]
        self.assertEqual(report["analysis_comparison"]["baseline_source"], "cleared_analysis")
        self.assertTrue(report["analysis_comparison"]["material_drop"])
