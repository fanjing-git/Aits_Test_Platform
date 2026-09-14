"""Focused adapter integration tests for T155A segmented structured calls."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from apps.requirement_analysis.llm_adapter import ModelAnalysisError, RequirementModelAdapter


class SegmentedRequirementAdapterTests(SimpleTestCase):
    """Verify the shared batch runtime is visible to a real model adapter."""

    @staticmethod
    def _adapter(runtime: Mock) -> RequirementModelAdapter:
        manager = Mock()
        manager.execute_with_fallback.side_effect = lambda _task, operation, **_kwargs: operation(runtime, SimpleNamespace(parameters={"structured_segment_items": 1}, name="fake"))
        prompts = Mock()
        prompts.resolve.return_value = SimpleNamespace(content="JSON")
        return RequirementModelAdapter(model_manager=manager, prompt_manager=prompts)

    def test_requirement_output_contains_segment_trace_and_merges_results(self) -> None:
        runtime = Mock()

        def generate(**kwargs):
            evidence = kwargs["evidence"]
            evidence_id = evidence[0]["id"]
            evidence_text = evidence[0]["text"]
            return {
                "modules": [{"id": f"module-{evidence_id}", "name": evidence_text, "evidence_ids": [evidence_id]}],
                "functions": [{"id": f"function-{evidence_id}", "name": evidence_text, "evidence_ids": [evidence_id]}],
                "linkages": [],
                "test_points": [{"id": f"point-{evidence_id}", "description": evidence_text, "evidence_ids": [evidence_id]}],
                "coverage_report": {},
            }

        runtime.generate_structured.side_effect = generate
        result = self._adapter(runtime).analyze(
            text="需求正文",
            evidence=[{"id": "e-1", "text": "订单"}, {"id": "e-2", "text": "支付"}],
        )
        trace = result["coverage_report"]["structured_generation"]
        self.assertEqual(trace["status"], "completed")
        self.assertEqual(trace["segment_count"], 2)
        self.assertEqual(len(result["functions"]), 2)

    def test_output_truncation_is_replanned_into_smaller_segments(self) -> None:
        runtime = Mock()
        first = True

        def generate(**kwargs):
            nonlocal first
            evidence = kwargs["evidence"]
            if first and len(evidence) > 1:
                first = False
                raise ModelAnalysisError("截断", code="output_truncated")
            evidence_id = evidence[0]["id"]
            evidence_text = evidence[0]["text"]
            return {
                "modules": [{"id": f"module-{evidence_id}", "name": evidence_text, "evidence_ids": [evidence_id]}],
                "functions": [{"id": f"function-{evidence_id}", "name": evidence_text, "evidence_ids": [evidence_id]}],
                "linkages": [],
                "test_points": [],
                "coverage_report": {},
            }

        runtime.generate_structured.side_effect = generate
        manager = Mock()
        manager.execute_with_fallback.side_effect = lambda _task, operation, **_kwargs: operation(runtime, SimpleNamespace(parameters={"structured_segment_items": 2}, name="fake"))
        prompts = Mock(); prompts.resolve.return_value = SimpleNamespace(content="JSON")
        result = RequirementModelAdapter(model_manager=manager, prompt_manager=prompts).analyze(
            text="需求正文",
            evidence=[{"id": "e-1", "text": "订单"}, {"id": "e-2", "text": "支付"}],
        )
        statuses = [item["status"] for item in result["coverage_report"]["structured_generation"]["segments"]]
        self.assertIn("split_after_output_truncated", statuses)
        self.assertEqual(len(result["functions"]), 2)
