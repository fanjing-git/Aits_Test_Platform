"""Focused T052 business-linkage recognition tests."""

from types import SimpleNamespace
from unittest.mock import Mock

from django.test import TestCase

from apps.business_linkage.linkage_analyzer import (
    BusinessLinkageAnalysisError,
    BusinessLinkageAnalyzer,
)
from core.llm.manager import ModelFallbackExhausted


def valid_payload() -> dict[str, object]:
    """Return a representative evidence-grounded linkage response."""
    return {
        "linkages": [
            {
                "id": "checkout-flow",
                "name": "下单支付流程",
                "description": "创建订单后完成支付并查询状态。",
                "evidence_ids": ["login", "order", "pay"],
                "steps": [
                    {"id": "step-login", "interface_id": "login", "order": 1, "purpose": "获取登录令牌", "evidence_ids": ["login"]},
                    {"id": "step-order", "interface_id": "order", "order": 2, "purpose": "创建订单", "evidence_ids": ["order"]},
                    {"id": "step-pay", "interface_id": "pay", "order": 3, "purpose": "支付订单", "evidence_ids": ["pay"]},
                ],
                "dependencies": [
                    {"id": "dep-login-order", "from_step_id": "step-login", "to_step_id": "step-order", "data_mappings": [{"from": "token", "to": "Authorization"}], "evidence_ids": ["login", "order"]},
                    {"id": "dep-order-pay", "from_step_id": "step-order", "to_step_id": "step-pay", "data_mappings": [{"from": "order_id", "to": "order_id"}], "evidence_ids": ["order", "pay"]},
                ],
            }
        ],
        "coverage_report": {"confidence": 0.92},
    }


class FakeLinkageManager:
    """Execute the routed operation with an injected runtime and safe config."""

    def __init__(self, runtime: Mock) -> None:
        self.runtime = runtime
        self.calls: list[tuple[object, dict[str, object]]] = []

    def execute_routed(self, feature_key: object, operation: object, **kwargs: object) -> object:
        """Record the route and execute it once without network access."""
        self.calls.append((feature_key, dict(kwargs)))
        config = SimpleNamespace(
            name="fake-linkage-model",
            provider="local",
            model_name="fake-model",
            parameters={"structured_input_chars": 24000, "structured_segment_items": 32},
        )
        return operation(self.runtime, config)


class BusinessLinkageAnalyzerTests(TestCase):
    """Verify T052 recognition, evidence boundaries and safe failures."""

    def documents(self) -> list[dict[str, object]]:
        """Return minimal interface definitions for the test workflow."""
        return [
            {"id": "login", "method": "POST", "path": "/login", "response_schema": {"token": "string"}, "password": "do-not-send"},
            {"id": "order", "method": "POST", "path": "/orders", "request_schema": {"Authorization": "bearer", "sku": "string"}},
            {"id": "pay", "method": "POST", "path": "/payments", "request_schema": {"order_id": "string"}},
        ]

    def test_valid_response_is_normalized_and_uses_api_prompt_route(self) -> None:
        runtime = Mock()
        runtime.generate_structured.return_value = valid_payload()
        manager = FakeLinkageManager(runtime)

        result = BusinessLinkageAnalyzer(model_manager=manager).analyze(
            api_documents=self.documents(), project_name="checkout"
        )

        self.assertEqual(len(result["linkages"]), 1)
        self.assertEqual(result["linkages"][0]["test_case_ids"], [])
        self.assertEqual(result["linkages"][0]["steps"][0]["interface_id"], "login")
        self.assertEqual(result["coverage_report"]["uncovered_interface_ids"], [])
        self.assertEqual(manager.calls[0][1]["task_type"], "business_linkage")
        prompt = runtime.generate_structured.call_args.kwargs["prompt"]
        self.assertIn("linkages", prompt)

    def test_sensitive_values_are_redacted_before_model_call(self) -> None:
        runtime = Mock()
        runtime.generate_structured.return_value = {"linkages": [], "coverage_report": {}}
        manager = FakeLinkageManager(runtime)

        BusinessLinkageAnalyzer(model_manager=manager).analyze(api_documents=self.documents())

        call = runtime.generate_structured.call_args.kwargs
        self.assertNotIn("do-not-send", call["text"])
        self.assertNotIn("bearer", call["text"])
        self.assertIn("<redacted>", call["text"] + str(call["evidence"]))

    def test_hallucinated_interface_is_rejected(self) -> None:
        runtime = Mock()
        payload = valid_payload()
        payload["linkages"][0]["steps"][0]["interface_id"] = "not-in-doc"
        runtime.generate_structured.return_value = payload

        with self.assertRaises(BusinessLinkageAnalysisError) as raised:
            BusinessLinkageAnalyzer(model_manager=FakeLinkageManager(runtime)).analyze(api_documents=self.documents())

        self.assertEqual(raised.exception.code, "invalid_response")

    def test_empty_input_and_model_failure_are_explicit_and_sanitized(self) -> None:
        with self.assertRaises(BusinessLinkageAnalysisError) as empty:
            BusinessLinkageAnalyzer(model_manager=FakeLinkageManager(Mock())).analyze(api_documents=[])
        self.assertEqual(empty.exception.code, "empty_input")

        class FailingManager:
            """Simulate all routed models failing without exposing the cause."""

            def execute_routed(self, *args: object, **kwargs: object) -> object:
                """Raise the shared exhaustion error with sensitive provider text."""
                raise ModelFallbackExhausted(("primary",), last_error=OSError("secret-api-key"))

        with self.assertRaises(BusinessLinkageAnalysisError) as failed:
            BusinessLinkageAnalyzer(model_manager=FailingManager()).analyze(api_documents=self.documents())
        self.assertEqual(failed.exception.code, "model_error")
        self.assertNotIn("secret-api-key", str(failed.exception))
