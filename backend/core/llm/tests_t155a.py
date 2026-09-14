"""Focused tests for bounded segmented structured execution."""

from __future__ import annotations

from unittest import TestCase

from core.llm.structured_runtime import (
    StructuredSegment,
    execute_structured_segments,
    merge_structured_payloads,
    plan_structured_segments,
)


class OutputTruncatedError(RuntimeError):
    """Fake provider truncation with the same stable code as ProviderError."""

    code = "output_truncated"


class StructuredRuntimeTests(TestCase):
    """Verify segmentation, bounded recovery and deterministic merging."""

    def test_plan_preserves_order_and_splits_evidence(self) -> None:
        evidence = tuple({"id": f"e-{index}", "text": "证据"} for index in range(5))
        segments = plan_structured_segments("需求正文", evidence, max_input_chars=2000, max_evidence_items=2)
        self.assertEqual([item["id"] for segment in segments for item in segment.evidence], [f"e-{index}" for index in range(5)])
        self.assertEqual(len(segments), 3)

    def test_output_truncation_splits_segment_without_unbounded_retry(self) -> None:
        original = StructuredSegment("segment-0001", "需求正文", tuple({"id": f"e-{index}"} for index in range(4)))
        calls: list[str] = []

        def call(segment: StructuredSegment) -> dict[str, object]:
            calls.append(segment.segment_id)
            if segment.segment_id == "segment-0001":
                raise OutputTruncatedError("truncated")
            return {
                "modules": [{"id": "module-1", "name": segment.segment_id}],
                "functions": [{"id": "function-1", "module_id": "module-1", "name": segment.segment_id}],
                "coverage_report": {},
            }

        result = execute_structured_segments((original,), call)
        self.assertEqual(calls[0], "segment-0001")
        self.assertEqual(result.trace[0]["status"], "split_after_output_truncated")
        self.assertEqual(result.trace[-1]["status"], "completed")
        self.assertEqual(len(result.payload["modules"]), 2)
        self.assertLessEqual(len(calls), 3)

    def test_merge_repairs_colliding_ids_and_known_references(self) -> None:
        first = StructuredSegment("segment-0001", "a", ())
        second = StructuredSegment("segment-0002", "b", ())
        merged = merge_structured_payloads((
            (first, {"functions": [{"id": "function-1", "name": "A"}]}),
            (second, {"functions": [{"id": "function-1", "name": "B"}], "test_points": [{"id": "point-1", "function_id": "function-1"}]}),
        ))
        self.assertEqual([item["id"] for item in merged["functions"]], ["function-1", "function-1__segment-0002"])
        self.assertEqual(merged["test_points"][0]["function_id"], "function-1__segment-0002")
        self.assertEqual(merged["test_points"][0]["source_segment_id"], "segment-0002")
