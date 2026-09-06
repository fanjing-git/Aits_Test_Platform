"""Focused tests for five-round generated case review."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.case_generation.generator import generate_document_cases
from apps.case_generation.models import CaseGenerationRecord
from apps.case_generation.reviewer import CaseReviewError, review_cases, review_generation_record
from apps.projects.models import Project
from apps.requirement_analysis.analyzer import analyze_requirement_document
from apps.requirement_analysis.models import RequirementDocument


class CaseReviewTests(TestCase):
    """Verify review evidence, approval and safe rejection."""

    def setUp(self) -> None:
        user = get_user_model().objects.create_user(username="case-review-owner")
        project = Project.objects.create(name="Case review project", created_by=user)
        document = RequirementDocument.objects.create(project=project, title="Login", content_text="用户可以登录系统。", created_by=user)
        analysis = analyze_requirement_document(document)
        self.record = generate_document_cases(document, analysis)

    def test_review_runs_five_rounds_and_persists_report(self) -> None:
        reviewed = review_generation_record(self.record)
        self.assertEqual(reviewed.review_rounds, 5)
        self.assertTrue(reviewed.review_report["approved"])
        self.assertEqual(reviewed.status, CaseGenerationRecord.Status.COMPLETED)
        self.assertEqual(len(reviewed.review_report["round_trace"]), 5)

    def test_review_rejects_missing_cases(self) -> None:
        self.record.cases = []
        with self.assertRaises(CaseReviewError): review_cases(self.record)

    def test_review_failure_is_retained_for_audit(self) -> None:
        self.record.cases = []
        with self.assertRaises(CaseReviewError): review_generation_record(self.record)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, CaseGenerationRecord.Status.FAILED)
