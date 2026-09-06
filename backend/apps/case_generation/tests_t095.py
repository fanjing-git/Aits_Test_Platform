"""API tests for the T095 case-generation workbench."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.case_generation.models import CaseGenerationRecord
from apps.projects.models import Project, ProjectMember
from apps.requirement_analysis.analyzer import analyze_requirement_document
from apps.requirement_analysis.models import RequirementDocument


class CaseGenerationApiTests(TestCase):
    """Verify generation, review, selection and project isolation."""

    def setUp(self) -> None:
        User = get_user_model()
        self.owner = User.objects.create_user(username="t095-owner")
        self.viewer = User.objects.create_user(username="t095-viewer")
        self.outsider = User.objects.create_user(username="t095-outsider")
        self.project = Project.objects.create(name="T095 project", created_by=self.owner)
        ProjectMember.objects.create(project=self.project, user=self.viewer, role=ProjectMember.Role.VIEWER)
        self.document = RequirementDocument.objects.create(project=self.project, title="登录", content_text="用户登录系统。", created_by=self.owner)
        analyze_requirement_document(self.document)
        self.url = "/api/case-generation/"
        self.client = APIClient()

    def test_owner_can_generate_review_and_select(self) -> None:
        self.client.force_authenticate(self.owner)
        created = self.client.post(self.url, {"document": str(self.document.pk)}, format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        record_id = created.data["id"]
        self.assertGreater(created.data["total_cases"], 0)
        reviewed = self.client.post(f"{self.url}{record_id}/review/")
        self.assertEqual(reviewed.status_code, status.HTTP_200_OK)
        selected = self.client.post(f"{self.url}{record_id}/select/")
        self.assertEqual(selected.status_code, status.HTTP_200_OK)
        self.assertIn("automation_selection", selected.data["coverage_report"])

    def test_viewer_reads_but_cannot_mutate_and_outsider_is_hidden(self) -> None:
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(self.url, {"document": str(self.document.pk)}, format="json").status_code, status.HTTP_201_CREATED)
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.post(self.url, {"document": str(self.document.pk)}, format="json").status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.url).data, [])

    def test_generation_requires_completed_analysis_and_login(self) -> None:
        pending = RequirementDocument.objects.create(project=self.project, title="未分析", content_text="内容", created_by=self.owner)
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.url, {"document": str(pending.pk)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED)
