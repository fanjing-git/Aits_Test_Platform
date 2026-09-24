"""Focused T170 tests for requirement analysis, review and decomposition Skills."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.projects.models import Project, ProjectMember
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument
from apps.requirement_analysis.tasks import run_requirement_decomposition, run_requirement_review
from apps.skills.business_execution import BusinessSkillRunService
from apps.skills.models import SkillChainRun
from apps.users.models import UserProfile


class RequirementSkillT170Tests(TestCase):
    """Verify the three-stage gate and shared sync/async service contract."""

    def setUp(self) -> None:
        self.owner = get_user_model().objects.create_user(username="t170-owner")
        self.owner.profile.role = UserProfile.Role.TEST_LEADER
        self.owner.profile.save(update_fields=("role",))
        self.viewer = get_user_model().objects.create_user(username="t170-viewer")
        self.project = Project.objects.create(name="T170 project", created_by=self.owner)
        ProjectMember.objects.create(project=self.project, user=self.viewer, role=ProjectMember.Role.VIEWER)
        self.document = RequirementDocument.objects.create(
            project=self.project,
            title="需求技能链",
            content_text="用户登录后查看订单，系统保存订单数据。",
            created_by=self.owner,
        )
        self.analysis = RequirementAnalysis.objects.create(
            document=self.document,
            modules=[{"id": "module-1", "name": "订单", "summary": "订单管理"}],
            functions=[{
                "id": "module-1-function-1", "module_id": "module-1", "name": "查看订单",
                "description": "用户查看订单", "acceptance_criteria": ["返回可验证订单列表"], "evidence_ids": ["e-1"],
            }],
            linkages=[],
            test_points=[{
                "id": "test-point-1", "function_id": "module-1-function-1", "type": "positive",
                "description": "用户可以查看订单", "evidence_ids": ["e-1"],
            }],
            coverage_report={"data_flows": [{"data": ["订单"], "from": "module-1-function-1", "to": "module-1-function-1"}]},
            analysis_fingerprint="analysis-t170-v1",
            quality_status=RequirementAnalysis.QualityStatus.COMPLETE,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_decomposition_requires_review_and_persists_traceable_artifact(self) -> None:
        url = f"/api/requirement-documents/{self.document.pk}/"
        blocked = self.client.post(f"{url}decompose-requirement/", {}, format="json")
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("已通过需求评审", blocked.data["detail"])

        reviewed = self.client.post(f"{url}review-requirement/", {}, format="json")
        self.assertEqual(reviewed.status_code, status.HTTP_200_OK)
        self.assertEqual(reviewed.data["latest_analysis"]["review_status"], "passed")
        self.assertTrue(reviewed.data["latest_analysis"]["review_run"])

        decomposed = self.client.post(f"{url}decompose-requirement/", {}, format="json")
        self.assertEqual(decomposed.status_code, status.HTTP_200_OK)
        artifact = decomposed.data["latest_analysis"]["decomposition"]
        self.assertEqual(decomposed.data["latest_analysis"]["decomposition_status"], "completed")
        self.assertEqual(artifact["source_analysis_id"], str(self.analysis.pk))
        self.assertEqual(artifact["modules"][0]["id"], "module-1")
        self.assertTrue(artifact["acceptance_conditions"])
        saved = RequirementAnalysis.objects.get(pk=self.analysis.pk)
        self.assertEqual(SkillChainRun.objects.get(pk=saved.review_run_id).status, SkillChainRun.Status.COMPLETED)
        self.assertEqual(SkillChainRun.objects.get(pk=saved.decomposition_run_id).status, SkillChainRun.Status.COMPLETED)

    def test_async_tasks_use_same_service_and_enforce_review_gate(self) -> None:
        review_run = BusinessSkillRunService().start(
            user=self.owner, project_id=self.project.pk, workflow_key="requirement_review",
            operation="requirement_review", business_type="requirement_analysis", business_id=self.analysis.pk,
            input_snapshot={"analysis_id": str(self.analysis.pk)}, node_id="requirement_review", skill_name="需求评审",
        )
        result = run_requirement_review.run(str(self.document.pk), str(review_run.pk))
        self.assertEqual(result["status"], "completed")
        self.analysis.refresh_from_db()
        decomposition_run = BusinessSkillRunService().start(
            user=self.owner, project_id=self.project.pk, workflow_key="requirement_decomposition",
            operation="requirement_decomposition", business_type="requirement_analysis", business_id=self.analysis.pk,
            input_snapshot={"analysis_id": str(self.analysis.pk)}, node_id="requirement_decomposition", skill_name="需求拆解",
        )
        result = run_requirement_decomposition.run(str(self.document.pk), str(decomposition_run.pk))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(SkillChainRun.objects.get(pk=decomposition_run.pk).status, SkillChainRun.Status.COMPLETED)

    def test_review_failure_is_persisted_and_does_not_create_decomposition(self) -> None:
        self.analysis.functions = [{"id": "orphan", "module_id": "missing", "name": "孤立功能", "description": "x"}]
        self.analysis.save(update_fields=("functions",))
        response = self.client.post(f"/api/requirement-documents/{self.document.pk}/review-requirement/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.analysis.refresh_from_db()
        self.assertEqual(self.analysis.review_status, RequirementAnalysis.StageStatus.FAILED)
        self.assertEqual(self.analysis.decomposition_status, RequirementAnalysis.StageStatus.PENDING)
        self.assertEqual(SkillChainRun.objects.get(pk=self.analysis.review_run_id).status, SkillChainRun.Status.FAILED)

    def test_unauthenticated_and_viewer_are_rejected(self) -> None:
        url = f"/api/requirement-documents/{self.document.pk}/review-requirement/"
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(url, {}, format="json").status_code, status.HTTP_401_UNAUTHORIZED)
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.post(url, {}, format="json").status_code, status.HTTP_403_FORBIDDEN)
