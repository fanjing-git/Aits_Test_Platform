"""Focused tests for the five-round case generation pipeline."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.case_generation.generator import CaseGenerationError, generate_cases, generate_document_cases
from apps.case_generation.models import CaseGenerationRecord
from apps.projects.models import Project
from apps.requirement_analysis.analyzer import analyze_requirement_document
from apps.requirement_analysis.linkages import identify_document_linkages
from apps.requirement_analysis.models import RequirementDocument


class CaseGenerationTests(TestCase):
    """Verify round trace, coverage and persisted generation output."""

    def test_five_rounds_cover_function_and_linkage_scenarios(self) -> None:
        payload = {"functions": [{"id": "account-login", "module_id": "account", "name": "用户登录"}, {"id": "order-create", "module_id": "order", "name": "创建订单"}], "linkages": [{"id": "link-1", "from": "account-login", "to": "order-create"}]}
        result = generate_cases(payload)
        self.assertEqual([item["round"] for item in result.round_trace], [1, 2, 3, 4, 5])
        self.assertEqual(result.coverage_report["coverage_rate"], 1.0)
        self.assertEqual({item["type"] for item in result.cases}, {"positive", "negative", "boundary", "linkage"})

    def test_missing_functions_fail_safely(self) -> None:
        with self.assertRaises(CaseGenerationError): generate_cases({"functions": []})

    def test_document_generation_persists_completed_record(self) -> None:
        user = get_user_model().objects.create_user(username="case-generator-owner")
        project = Project.objects.create(name="Case generator project", created_by=user)
        document = RequirementDocument.objects.create(project=project, title="Order", content_text="# Account\n用户登录。\n# Order\n系统创建订单。", created_by=user)
        analysis = analyze_requirement_document(document)
        identify_document_linkages(analysis)
        record = generate_document_cases(document, analysis)
        self.assertEqual(record.status, CaseGenerationRecord.Status.COMPLETED)
        self.assertEqual(record.rounds, 5)
        self.assertGreater(record.total_cases, 0)
        self.assertEqual(record.coverage_report["coverage_rate"], 1.0)
