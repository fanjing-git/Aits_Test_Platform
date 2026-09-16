"""Focused T053 multi-interface case generation tests."""

from django.test import SimpleTestCase

from apps.business_linkage.case_generator import (
    BusinessLinkageCaseGenerationError,
    generate_linkage_cases,
)


def linkage(identifier: str = "checkout") -> dict[str, object]:
    """Return a representative T052 linkage payload."""
    return {
        "id": identifier,
        "name": "下单支付流程",
        "description": "登录后创建订单并完成支付。",
        "steps": [
            {"id": "step-login", "interface_id": "login", "order": 1, "purpose": "获取令牌"},
            {"id": "step-order", "interface_id": "order", "order": 2, "purpose": "创建订单"},
            {"id": "step-pay", "interface_id": "pay", "order": 3, "purpose": "完成支付"},
        ],
        "dependencies": [
            {"id": "dep-login-order", "from_step_id": "step-login", "to_step_id": "step-order"},
            {"id": "dep-order-pay", "from_step_id": "step-order", "to_step_id": "step-pay"},
        ],
    }


class BusinessLinkageCaseGeneratorTests(SimpleTestCase):
    """Verify T053 output is chained, stable and bounded."""

    def test_generates_ordered_primary_flow_for_each_linkage(self) -> None:
        result = generate_linkage_cases([linkage("b-flow"), linkage("a-flow")])

        self.assertEqual(result.coverage_report["case_count"], 2)
        self.assertEqual([case["linkage_id"] for case in result.cases], ["a-flow", "b-flow"])
        self.assertEqual(
            result.cases[0]["steps"],
            [
                "第1步：调用接口 login，获取令牌",
                "第2步：调用接口 order，创建订单",
                "第3步：调用接口 pay，完成支付",
            ],
        )
        self.assertFalse(result.cases[0]["automatable"])

    def test_marks_t054_data_flow_and_assertions_as_pending(self) -> None:
        result = generate_linkage_cases([linkage()])

        self.assertEqual(result.coverage_report["data_flow_status"], "pending_t054")
        self.assertEqual(result.coverage_report["assertion_status"], "pending_t054")
        self.assertEqual(result.cases[0]["automation_pending"], "T054_data_flow_and_assertions")
        self.assertNotIn("secret", str(result))

    def test_rejects_empty_duplicate_and_invalid_dependency_inputs(self) -> None:
        with self.assertRaises(BusinessLinkageCaseGenerationError) as empty:
            generate_linkage_cases([])
        self.assertEqual(empty.exception.code, "empty_input")

        with self.assertRaises(BusinessLinkageCaseGenerationError):
            generate_linkage_cases([linkage(), linkage()])

        invalid = linkage()
        invalid["dependencies"] = [{"id": "bad", "from_step_id": "step-login", "to_step_id": "missing"}]
        with self.assertRaises(BusinessLinkageCaseGenerationError):
            generate_linkage_cases([invalid])
