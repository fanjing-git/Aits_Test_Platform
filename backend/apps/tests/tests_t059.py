"""T059 REST, authorization, execution persistence, and project isolation tests."""

import os
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.environments.models import Environment
from apps.projects.models import Project, ProjectMember
from apps.tests.executor.base import ExecutionResult
from apps.tests.models import TestCase as TestCaseModel, TestResult, TestRun


class TestExecutionAPITests(TestCase):
    """Exercise the complete T059 API surface without contacting external targets."""

    def setUp(self) -> None:
        """Create project roles, an encrypted environment, and one API case."""
        self.key_patch = patch.dict(os.environ, {"MODEL_CONFIG_FERNET_KEY": Fernet.generate_key().decode()})
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="t059-owner")
        self.viewer = user_model.objects.create_user(username="t059-viewer")
        self.other = user_model.objects.create_user(username="t059-other")
        self.owner.profile.role = "test_leader"
        self.owner.profile.save(update_fields=["role"])
        self.viewer.profile.role = "viewer"
        self.viewer.profile.save(update_fields=["role"])
        self.project = Project.objects.create(name="T059 API project", created_by=self.owner)
        self.other_project = Project.objects.create(name="T059 other project", created_by=self.other)
        ProjectMember.objects.create(project=self.project, user=self.owner, role=ProjectMember.Role.OWNER)
        ProjectMember.objects.create(project=self.project, user=self.viewer, role=ProjectMember.Role.VIEWER)
        ProjectMember.objects.create(project=self.other_project, user=self.other, role=ProjectMember.Role.OWNER)
        self.environment = Environment.objects.create(
            project=self.project,
            name=Environment.Name.TEST,
            base_url="http://127.0.0.1:8000",
            status=Environment.Status.AVAILABLE,
        )
        self.case = TestCaseModel.objects.create(
            project=self.project,
            case_id="T059-001",
            title="健康接口返回成功",
            steps=[{"method": "GET", "path": "/api/health/", "expected_status": 200}],
            expected_result="返回 200",
            case_type=TestCaseModel.CaseType.API,
        )
        self.client = APIClient()

    def test_case_list_is_empty_for_unrelated_project_and_requires_auth(self) -> None:
        """A visible member gets data while an unrelated project cannot leak cases."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.get("/api/test-cases/", {"project": str(self.other_project.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get("/api/test-cases/").status_code, 401)

    def test_case_create_validates_json_and_viewer_cannot_write(self) -> None:
        """Case creation works for a project author and rejects malformed or forbidden writes."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            "/api/test-cases/",
            {
                "project_id": str(self.project.pk),
                "case_id": "T059-002",
                "title": "字段错误反馈",
                "steps": {},
                "expected_result": "返回错误",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("steps", response.data)
        response = self.client.post(
            "/api/test-cases/",
            {
                "project_id": str(self.project.pk),
                "case_id": "T059-002",
                "title": "字段错误反馈",
                "steps": [],
                "expected_result": "返回错误",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.client.force_authenticate(user=self.viewer)
        response = self.client.post(
            "/api/test-cases/",
            {
                "project_id": str(self.project.pk),
                "case_id": "T059-003",
                "title": "不应创建",
                "expected_result": "禁止",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_run_create_execute_and_result_query_are_closed_loop(self) -> None:
        """Create a run, persist an executor result, and expose only safe result fields."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            "/api/test-runs/",
            {
                "project_id": str(self.project.pk),
                "environment_id": str(self.environment.pk),
                "name": "T059 本地健康检查",
                "mode": "immediate",
                "test_case_ids": [str(self.case.pk)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        run_id = response.data["id"]
        self.assertEqual(response.data["status"], "pending")
        result = ExecutionResult(
            status="passed",
            exit_code=0,
            passed=1,
            duration_ms=12,
            details=[{
                "case_id": self.case.case_id,
                "status": "passed",
                "duration_ms": 12,
                "status_code": 200,
                "response_summary": {"status_code": 200, "json_keys": ["status"]},
                "assertions": [{"kind": "status_code", "passed": True}],
            }],
        )
        with patch("apps.tests.services.APIExecutor.execute", return_value=result):
            response = self.client.post(f"/api/test-runs/{run_id}/execute/", format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "completed")
        self.assertEqual(response.data["result_counts"]["passed"], 1)
        self.assertNotIn("json_body", response.data["results"][0]["response_summary"])
        self.assertEqual(TestResult.objects.get(run_id=run_id).status, TestResult.Status.PASSED)
        detail = self.client.get(f"/api/test-runs/{run_id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.data["results"]), 1)
        result_list = self.client.get(f"/api/test-runs/{run_id}/results/")
        self.assertEqual(result_list.status_code, 200)
        self.assertEqual(result_list.data[0]["case_id"], self.case.case_id)

    def test_run_rejects_cross_project_environment_and_handles_executor_failure(self) -> None:
        """Reject resource mixing and persist a safe failure when no environment is selected."""
        other_environment = Environment.objects.create(
            project=self.other_project,
            name=Environment.Name.TEST,
            base_url="http://127.0.0.1:8000",
            status=Environment.Status.AVAILABLE,
        )
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            "/api/test-runs/",
            {
                "project_id": str(self.project.pk),
                "environment_id": str(other_environment.pk),
                "name": "跨项目执行",
                "mode": "immediate",
                "test_case_ids": [str(self.case.pk)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            "/api/test-runs/",
            {
                "project_id": str(self.project.pk),
                "name": "缺少环境",
                "mode": "immediate",
                "test_case_ids": [str(self.case.pk)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        run_id = response.data["id"]
        response = self.client.post(f"/api/test-runs/{run_id}/execute/", format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "failed")
        self.assertEqual(response.data["summary"]["error_code"], "environment_not_selected")
