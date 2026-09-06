"""Focused tests for automation suitability selection."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.case_generation.generator import generate_document_cases
from apps.case_generation.models import CaseGenerationRecord
from apps.case_generation.reviewer import review_generation_record
from apps.case_generation.selector import CaseSelectionError, select_automatable_cases, select_generation_record
from apps.projects.models import Project
from apps.requirement_analysis.analyzer import analyze_requirement_document
from apps.requirement_analysis.models import RequirementDocument


class CaseSelectionTests(TestCase):
    """Verify automation, difficulty, stack and priority labels."""

    def test_classifies_manual_linkage_and_api_cases(self) -> None:
        result = select_automatable_cases([
            {"id": "case-001", "type": "positive", "title": "API login", "steps": ["call API"]},
            {"id": "case-002", "type": "linkage", "title": "Order display", "steps": ["open page", "verify screenshot"], "linkage_id": "link-1"},
        ])
        self.assertEqual(result.summary["automatable"], 1)
        self.assertEqual(result.cases[0]["recommended_stack"], ["pytest", "requests"])
        self.assertFalse(result.cases[1]["automatable"])
        self.assertEqual(result.cases[1]["automation_difficulty"], "high")

    def test_empty_cases_fail_safely(self) -> None:
        with self.assertRaises(CaseSelectionError): select_automatable_cases([])

    def test_selection_updates_generation_record_counts(self) -> None:
        user = get_user_model().objects.create_user(username="case-selector-owner")
        project = Project.objects.create(name="Case selector project", created_by=user)
        document = RequirementDocument.objects.create(project=project, title="Login", content_text="用户可以登录系统。", created_by=user)
        analysis = analyze_requirement_document(document)
        record = generate_document_cases(document, analysis)
        review_generation_record(record)
        updated = select_generation_record(record)
        self.assertEqual(updated.auto_cases + updated.manual_cases, updated.total_cases)
        self.assertIn("automation_selection", updated.coverage_report)
        self.assertEqual(updated.status, CaseGenerationRecord.Status.COMPLETED)
