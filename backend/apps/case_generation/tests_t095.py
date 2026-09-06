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

    def test_repeated_review_and_selection_are_idempotent(self) -> None:
        self.client.force_authenticate(self.owner)
        created = self.client.post(self.url, {"document": str(self.document.pk)}, format="json")
        record_id = created.data["id"]
        first_review = self.client.post(f"{self.url}{record_id}/review/")
        second_review = self.client.post(f"{self.url}{record_id}/review/")
        self.assertEqual(first_review.status_code, status.HTTP_200_OK)
        self.assertEqual(second_review.status_code, status.HTTP_200_OK)
        self.assertEqual(second_review.data["review_report"], first_review.data["review_report"])
        first_select = self.client.post(f"{self.url}{record_id}/select/")
        second_select = self.client.post(f"{self.url}{record_id}/select/")
        self.assertEqual(second_select.status_code, status.HTTP_200_OK)
        self.assertEqual(second_select.data["coverage_report"]["automation_selection"], first_select.data["coverage_report"]["automation_selection"])

    def test_legacy_english_review_issues_are_localized_on_read(self) -> None:
        record = CaseGenerationRecord.objects.create(
            project=self.project,
            document=self.document,
            cases=[{"id": "case-001", "title": "登录", "type": "positive", "steps": ["执行"], "expected_result": "成功"}],
            review_rounds=5,
            review_report={"approved": False, "analysis_method": "model_verified", "issues": [{"id": "issue-1", "severity": "medium", "description": "Test case steps are generic and lack specific actions and data.", "suggestion": "Detail the steps with concrete actions, inputs, and expected outcomes."}]},
        )
        self.client.force_authenticate(self.owner)
        response = self.client.get(f"{self.url}{record.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        issue = response.data["review_report"]["issues"][0]
        self.assertEqual(issue["description"], "测试步骤过于笼统，缺少具体操作和测试数据。")

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
