"""Focused stage-27 tests for queued analysis progress and cancellation."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.projects.models import Project
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument
from apps.users.models import UserProfile


class RequirementTaskApiT157Tests(TestCase):
    """Verify the REST task lifecycle without requiring a live broker worker."""

    def setUp(self) -> None:
        self.owner = get_user_model().objects.create_user(username="t157-analysis-owner")
        self.owner.profile.role = UserProfile.Role.TEST_LEADER
        self.owner.profile.save(update_fields=("role",))
        self.project = Project.objects.create(name="T157 analysis project", created_by=self.owner)
        self.document = RequirementDocument.objects.create(
            project=self.project,
            title="任务进度需求",
            content_text="用户登录系统。",
            created_by=self.owner,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    @patch("apps.requirement_analysis.views.run_requirement_analysis.apply_async")
    def test_analyze_returns_pending_runtime_and_cancel_is_durable(self, apply_async) -> None:
        response = self.client.post(f"/api/requirement-documents/{self.document.pk}/analyze/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["task_runtime"]["status"], "pending")
        apply_async.assert_called_once()

        progress = self.client.get(f"/api/requirement-documents/{self.document.pk}/analysis-progress/")
        self.assertEqual(progress.status_code, status.HTTP_200_OK)
        self.assertEqual(progress.data["task_runtime"]["status"], "pending")

        cancelled = self.client.post(f"/api/requirement-documents/{self.document.pk}/cancel-analysis/", {}, format="json")
        self.assertEqual(cancelled.status_code, status.HTTP_200_OK)
        self.assertTrue(cancelled.data["task_runtime"]["cancel_requested"])
        self.assertEqual(cancelled.data["task_runtime"]["status"], "cancel_requested")

    def test_progress_prefers_terminal_runtime_after_worker_cancellation(self) -> None:
        self.document.analysis_baseline = {
            "_last_task_runtime": {
                "task_id": "cancelled-task",
                "task_type": "requirement_analysis",
                "status": "cancelled",
                "current_step": "已取消",
                "cancel_requested": True,
            }
        }
        self.document.status = RequirementDocument.Status.UPLOADED
        self.document.save(update_fields=("analysis_baseline", "status"))

        progress = self.client.get(f"/api/requirement-documents/{self.document.pk}/analysis-progress/")

        self.assertEqual(progress.status_code, status.HTTP_200_OK)
        self.assertEqual(progress.data["task_runtime"]["status"], "cancelled")
