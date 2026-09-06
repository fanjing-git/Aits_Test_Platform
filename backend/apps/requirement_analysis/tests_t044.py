"""Focused tests for cross-module linkage recognition."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.projects.models import Project
from apps.requirement_analysis.analyzer import analyze_requirement_document
from apps.requirement_analysis.linkages import LinkageAnalysisError, identify_document_linkages, identify_linkages
from apps.requirement_analysis.models import RequirementDocument


class RequirementLinkageTests(TestCase):
    """Verify explainable display, state and data linkage output."""

    def test_cross_module_relations_and_test_points(self) -> None:
        payload = {
            "modules": [{"id": "account"}, {"id": "orders"}],
            "functions": [
                {"id": "login", "module_id": "account", "name": "登录", "description": "用户登录后更新权限状态"},
                {"id": "order", "module_id": "orders", "name": "创建订单", "description": "创建订单并保存订单ID"},
                {"id": "order-view", "module_id": "orders", "name": "订单展示", "description": "页面展示订单状态"},
            ],
        }
        result = identify_linkages(payload)
        self.assertTrue(result.scenarios)
        self.assertTrue(any(item["relationship"] in {"state_link", "data_link", "display"} for item in result.scenarios))
        self.assertEqual(len(result.scenarios), len(result.test_points))

    def test_malformed_payload_is_rejected(self) -> None:
        with self.assertRaises(LinkageAnalysisError): identify_linkages({})

    def test_document_linkages_are_persisted_without_overwriting_existing_tests(self) -> None:
        user = get_user_model().objects.create_user(username="linkage-owner")
        project = Project.objects.create(name="Linkage project", created_by=user)
        document = RequirementDocument.objects.create(project=project, title="Order", content_text="# Account\n用户登录后更新权限状态。\n# Orders\n系统展示订单状态。", created_by=user)
        analysis = analyze_requirement_document(document)
        original_count = len(analysis.test_points)
        updated = identify_document_linkages(analysis)
        self.assertGreaterEqual(len(updated.linkages), 1)
        self.assertGreater(len(updated.test_points), original_count)
        updated.refresh_from_db()
        self.assertEqual(updated.coverage_report["cross_module_linkage_count"], len(updated.linkages))
