"""T155 analysis-record clearing tests."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.case_generation.models import CaseGenerationRecord
from apps.projects.models import Project, ProjectMember
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument


class RequirementAnalysisClearTests(TestCase):
    """Verify source preservation, idempotency and permission boundaries."""

    def setUp(self) -> None:
        self.client = APIClient()
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="t155-clear-owner")
        self.viewer = user_model.objects.create_user(username="t155-clear-viewer")
        self.project = Project.objects.create(name="T155 clear project", created_by=self.owner)
        ProjectMember.objects.create(project=self.project, user=self.viewer, role=ProjectMember.Role.VIEWER)
        self.document = RequirementDocument.objects.create(
            project=self.project,
            title="清除记录需求",
            content_text="保留原文和解析证据",
            parse_evidence=[{"id": "source-1", "text": "登录按钮"}],
            parse_confidence=0.9,
            visual_analysis_report={"status": "completed", "analysis_method": "model_verified"},
            status=RequirementDocument.Status.ANALYZED,
            created_by=self.owner,
        )
        self.analysis = RequirementAnalysis.objects.create(
            document=self.document,
            modules=[{"id": "module-1", "name": "登录"}],
            functions=[{"id": "function-1", "name": "提交登录"}],
            linkages=[{"id": "linkage-1", "description": "登录后进入首页"}],
            test_points=[{"id": "point-1", "description": "验证登录"}],
            coverage_report={"analysis_method": "model_verified"},
        )
        self.case_record = CaseGenerationRecord.objects.create(
            project=self.project,
            document=self.document,
            status=CaseGenerationRecord.Status.COMPLETED,
            cases=[{"id": "case-1", "title": "历史用例"}],
        )
        self.url = f"/api/requirement-documents/{self.document.pk}/clear-analysis/"

    def test_clear_preserves_source_and_historical_case_records(self) -> None:
        self.client.force_authenticate(self.owner)

        response = self.client.post(self.url, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["cleared_analysis_count"], 1)
        self.assertTrue(response.data["visual_report_cleared"])
        self.assertTrue(response.data["source_preserved"])
        self.assertTrue(response.data["case_generation_records_preserved"])
        self.assertFalse(RequirementAnalysis.objects.filter(document=self.document).exists())
        document = RequirementDocument.objects.get(pk=self.document.pk)
        self.assertEqual(document.status, RequirementDocument.Status.UPLOADED)
        self.assertEqual(document.content_text, "保留原文和解析证据")
        self.assertEqual(document.parse_evidence[0]["id"], "source-1")
        self.assertEqual(document.visual_analysis_report, {})
        self.assertTrue(CaseGenerationRecord.objects.filter(pk=self.case_record.pk).exists())

    def test_clear_is_idempotent_when_no_records_remain(self) -> None:
        self.client.force_authenticate(self.owner)
        self.client.post(self.url, format="json")

        response = self.client.post(self.url, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["cleared_analysis_count"], 0)
        self.assertFalse(response.data["visual_report_cleared"])

    def test_viewer_cannot_clear_analysis_records(self) -> None:
        self.client.force_authenticate(self.viewer)

        response = self.client.post(self.url, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(RequirementAnalysis.objects.filter(pk=self.analysis.pk).exists())
