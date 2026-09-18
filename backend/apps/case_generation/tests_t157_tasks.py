"""Focused stage-27 tests for queued generation progress and cancellation."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.case_generation.models import CaseGenerationRecord
from apps.projects.models import Project
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument
from apps.users.models import UserProfile


class CaseTaskApiT157Tests(TestCase):
    """Verify that generation creates a visible task shell before worker execution."""

    def setUp(self) -> None:
        self.owner = get_user_model().objects.create_user(username="t157-case-owner")
        self.owner.profile.role = UserProfile.Role.TEST_LEADER
        self.owner.profile.save(update_fields=("role",))
        self.project = Project.objects.create(name="T157 case project", created_by=self.owner)
        self.document = RequirementDocument.objects.create(
            project=self.project,
            title="用例任务需求",
            content_text="用户登录系统。",
            created_by=self.owner,
        )
        self.analysis = RequirementAnalysis.objects.create(
            document=self.document,
            modules=[{"id": "module-1", "name": "账户"}],
            functions=[{"id": "function-1", "module_id": "module-1", "name": "登录"}],
            linkages=[],
            test_points=[{"id": "point-1", "function_id": "function-1", "description": "验证登录"}],
            coverage_report={"manual_confirmation": {"confirmed": True, "reviewed_test_point_ids": ["point-1"]}},
            quality_status=RequirementAnalysis.QualityStatus.COMPLETE,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    @patch("apps.case_generation.views.run_case_generation.apply_async")
    def test_generation_returns_task_runtime_and_cancel_updates_record(self, apply_async) -> None:
        response = self.client.post(
            "/api/case-generation/",
            {"document": str(self.document.pk), "reviewed_test_point_ids": ["point-1"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["task_runtime"]["status"], "pending")
        apply_async.assert_called_once()
        record_id = response.data["id"]
        record = CaseGenerationRecord.objects.get(pk=record_id)
        self.assertEqual(record.status, CaseGenerationRecord.Status.GENERATING)

        cancelled = self.client.post(f"/api/case-generation/{record_id}/cancel/", {}, format="json")
        self.assertEqual(cancelled.status_code, status.HTTP_200_OK)
        self.assertEqual(cancelled.data["task_runtime"]["status"], "cancel_requested")
        self.assertTrue(cancelled.data["task_runtime"]["cancel_requested"])
