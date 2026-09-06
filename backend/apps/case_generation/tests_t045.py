"""Focused tests for case generation record persistence."""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.case_generation.models import CaseGenerationRecord
from apps.projects.models import Project
from apps.requirement_analysis.models import RequirementDocument


class CaseGenerationRecordTests(TestCase):
    """Verify project/document scope and generation lifecycle fields."""

    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(username="case-generation-owner")
        self.project = Project.objects.create(name="Case generation project", created_by=self.user)
        self.document = RequirementDocument.objects.create(project=self.project, title="Login", content_text="User can login", created_by=self.user)

    def test_record_stores_counts_and_status(self) -> None:
        record = CaseGenerationRecord.objects.create(project=self.project, document=self.document, rounds=1, total_cases=3, auto_cases=2, manual_cases=1, cases=[{"id": "case-001"}], coverage_report={"coverage_rate": 1})
        self.assertEqual(record.status, CaseGenerationRecord.Status.GENERATING)
        self.assertEqual(str(record), "Login (generating)")

    def test_record_rejects_cross_project_document(self) -> None:
        other = Project.objects.create(name="Other project", created_by=self.user)
        record = CaseGenerationRecord(project=other, document=self.document)
        with self.assertRaises(ValidationError): record.full_clean()
