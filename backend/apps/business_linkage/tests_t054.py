"""Focused T054 data-flow and assertion design tests."""

from django.test import SimpleTestCase

from apps.business_linkage.case_generator import generate_linkage_cases
from apps.business_linkage.data_flow import (
    BusinessLinkageDataFlowError,
    design_linkage_data_flow,
)


def linkage() -> dict[str, object]:
    """Return a linkage with explicit token and identifier mappings."""
    return {
        "id": "checkout",
        "name": "下单支付流程",
        "steps": [
            {"id": "step-login", "interface_id": "login", "order": 1},
            {"id": "step-order", "interface_id": "order", "order": 2},
            {"id": "step-pay", "interface_id": "pay", "order": 3},
        ],
        "dependencies": [
            {
                "id": "dep-login-order",
                "from_step_id": "step-login",
                "to_step_id": "step-order",
                "data_mappings": [{"from": "token", "to": "Authorization", "example": "raw-token-must-not-copy"}],
            },
            {
                "id": "dep-order-pay",
                "from_step_id": "step-order",
                "to_step_id": "step-pay",
                "data_mappings": [{"from": "order_id", "to": "order_id"}],
            },
        ],
    }


class BusinessLinkageDataFlowTests(SimpleTestCase):
    """Verify T054 creates explicit, non-executing linkage design metadata."""

    def test_enriches_t053_case_with_flows_and_assertions(self) -> None:
        source_linkage = linkage()
        source_case = generate_linkage_cases([source_linkage]).cases
        result = design_linkage_data_flow([source_linkage], source_case)

        case = result.cases[0]
        self.assertEqual(result.coverage_report["data_flow_count"], 2)
        self.assertEqual(case["data_flow"][0]["transfer_type"], "token")
        self.assertEqual(case["data_flow"][0]["target"]["location"], "request.headers")
        self.assertEqual(case["data_flow"][1]["target"]["location"], "request.body")
        self.assertGreaterEqual(len(case["step_assertions"]), 3)
        self.assertEqual(len(case["final_assertions"]), 1)
        self.assertEqual(case["data_flow_status"], "designed")
        self.assertEqual(case["execution_design_status"], "ready_for_t057_api_executor")
        self.assertNotIn("raw-token-must-not-copy", str(result))

    def test_rejects_missing_mapping_and_reverse_dependency(self) -> None:
        source_linkage = linkage()
        source_case = generate_linkage_cases([source_linkage]).cases
        source_linkage["dependencies"][0]["data_mappings"] = []
        with self.assertRaises(BusinessLinkageDataFlowError) as missing:
            design_linkage_data_flow([source_linkage], source_case)
        self.assertEqual(missing.exception.code, "missing_data_mapping")

        reversed_linkage = linkage()
        reversed_linkage["dependencies"][0]["from_step_id"] = "step-order"
        reversed_linkage["dependencies"][0]["to_step_id"] = "step-login"
        with self.assertRaises(BusinessLinkageDataFlowError):
            design_linkage_data_flow([reversed_linkage], source_case)

    def test_requires_one_matching_case_per_linkage(self) -> None:
        with self.assertRaises(BusinessLinkageDataFlowError) as empty:
            design_linkage_data_flow([linkage()], [])
        self.assertEqual(empty.exception.code, "empty_input")

        source_case = generate_linkage_cases([linkage()]).cases[0]
        source_case["linkage_id"] = "unknown"
        with self.assertRaises(BusinessLinkageDataFlowError) as invalid:
            design_linkage_data_flow([linkage()], [source_case])
        self.assertEqual(invalid.exception.code, "invalid_case")
