"""API tests for the T094 requirement analysis workbench."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.projects.models import Project, ProjectMember
from apps.requirement_analysis.models import RequirementDocument
from apps.users.models import UserProfile


class RequirementAnalysisApiTests(TestCase):
    """Verify project isolation, source ingestion and analysis actions."""

    def setUp(self) -> None:
        self.client = APIClient()
        User = get_user_model()
        self.owner = User.objects.create_user(username="t094-owner")
        self.viewer = User.objects.create_user(username="t094-viewer")
        self.outsider = User.objects.create_user(username="t094-outsider")
        self.owner.profile.role = UserProfile.Role.TEST_LEADER
        self.owner.profile.save(update_fields=("role",))
        self.project = Project.objects.create(name="T094 project", created_by=self.owner)
        ProjectMember.objects.create(project=self.project, user=self.viewer, role=ProjectMember.Role.VIEWER)
        self.url = "/api/requirement-documents/"

    def test_owner_can_upload_parse_analyze_and_identify_linkages(self) -> None:
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            self.url,
            {
                "project": str(self.project.pk),
                "title": "登录与订单",
                "version": "1.0",
                "source_type": "file",
                "file": SimpleUploadedFile("requirements.md", b"# Account\nUser login.\n# Orders\nUser creates order.", content_type="text/markdown"),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        document_id = response.data["id"]
        parsed_action = self.client.post(f"{self.url}{document_id}/parse/")
        self.assertEqual(parsed_action.status_code, status.HTTP_200_OK)
        self.assertEqual(parsed_action.data["skill_execution"]["status"], "completed")
        parsed = self.client.get(f"{self.url}{document_id}/").data
        self.assertTrue(parsed["parse_evidence"])
        self.assertEqual(parsed["parse_confidence"], 1.0)
        analyzed = self.client.post(f"{self.url}{document_id}/analyze/")
        self.assertEqual(analyzed.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(analyzed.data["latest_analysis"])
        self.assertEqual(analyzed.data["skill_execution"]["status"], "completed")
        linkage = self.client.post(f"{self.url}{document_id}/linkages/")
        self.assertEqual(linkage.status_code, status.HTTP_200_OK)

    def test_manual_and_online_validation_is_actionable(self) -> None:
        self.client.force_authenticate(self.owner)
        missing = self.client.post(self.url, {"project": str(self.project.pk), "title": "Empty", "source_type": "manual"}, format="json")
        self.assertEqual(missing.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("content_text", missing.data)
        link = self.client.post(self.url, {"project": str(self.project.pk), "title": "Link", "source_type": "online_link"}, format="json")
        self.assertEqual(link.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("source_url", link.data)

    @override_settings(REQUIREMENT_DOCUMENT_MAX_BYTES=8)
    def test_upload_rejects_configured_size_limit_before_writing_file(self) -> None:
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            self.url,
            {
                "project": str(self.project.pk),
                "title": "Too large",
                "source_type": "file",
                "file": SimpleUploadedFile("large.md", b"123456789", content_type="text/markdown"),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("超过", str(response.data["file"]))
        self.assertFalse(RequirementDocument.objects.filter(title="Too large").exists())

    def test_parse_reports_missing_persisted_file_separately(self) -> None:
        document = RequirementDocument.objects.create(
            project=self.project,
            title="Missing upload",
            source_type=RequirementDocument.SourceType.FILE,
            file_path="E:/does-not-exist/requirement.md",
            created_by=self.owner,
        )
        self.client.force_authenticate(self.owner)
        response = self.client.post(f"{self.url}{document.pk}/parse/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("文件不存在", response.data["detail"])

    def test_viewer_reads_but_cannot_mutate_and_outsider_is_hidden(self) -> None:
        document = RequirementDocument.objects.create(project=self.project, title="Visible", content_text="A requirement", created_by=self.owner)
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.post(f"{self.url}{document.pk}/analyze/").status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.url).data, [])
        self.assertEqual(self.client.get(f"/api/requirement-analyses/?document={document.pk}").data, [])

    def test_analyze_and_linkage_require_prerequisites(self) -> None:
        self.client.force_authenticate(self.owner)
        document = RequirementDocument.objects.create(project=self.project, title="No content", created_by=self.owner)
        response = self.client.post(f"{self.url}{document.pk}/analyze/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.client.post(f"{self.url}{document.pk}/linkages/").status_code, status.HTTP_400_BAD_REQUEST)

    def test_empty_screenshot_source_is_rejected_by_model(self) -> None:
        document = RequirementDocument(project=self.project, title="Empty screenshot", source_type=RequirementDocument.SourceType.SCREENSHOT, created_by=self.owner)
        with self.assertRaises(ValidationError):
            document.full_clean()

    def test_screenshot_ocr_text_can_be_persisted_and_parsed(self) -> None:
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            self.url,
            {"project": str(self.project.pk), "title": "截图 OCR", "source_type": "screenshot", "content_text": "背包页面显示材料"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        document_id = response.data["id"]
        parsed = self.client.post(f"{self.url}{document_id}/parse/")
        self.assertEqual(parsed.status_code, status.HTTP_200_OK)
        self.assertEqual(parsed.data["content_text"], "背包页面显示材料")

    def test_anonymous_requests_are_unauthorized(self) -> None:
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_screenshot_analysis_rejects_non_screenshot_source(self) -> None:
        document = RequirementDocument.objects.create(project=self.project, title="Manual", content_text="内容", created_by=self.owner)
        self.client.force_authenticate(self.owner)
        response = self.client.post(f"{self.url}{document.pk}/screenshot-analysis/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
