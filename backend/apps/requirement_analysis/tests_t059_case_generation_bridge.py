"""Regression tests for the requirement-analysis to case-generation bridge."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.case_generation.generator import generate_document_cases
from apps.case_generation.models import CaseGenerationRecord
from apps.projects.models import Project, ProjectMember
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument
from apps.users.models import UserProfile


class RequirementAnalysisCaseGenerationBridgeTests(TestCase):
    """Verify reviewable analysis can be explicitly confirmed before generation."""

    def setUp(self) -> None:
        self.owner = get_user_model().objects.create_user(username="t059-bridge-owner")
        self.viewer = get_user_model().objects.create_user(username="t059-bridge-viewer")
        self.owner.profile.role = UserProfile.Role.TEST_LEADER
        self.owner.profile.save(update_fields=("role",))
        self.project = Project.objects.create(name="T059 bridge project", created_by=self.owner)
        ProjectMember.objects.create(project=self.project, user=self.viewer, role=ProjectMember.Role.VIEWER)
        self.document = RequirementDocument.objects.create(
            project=self.project,
            title="登录需求",
            content_text="用户可以使用账号和密码登录系统。",
            created_by=self.owner,
        )
        self.analysis = RequirementAnalysis.objects.create(
            document=self.document,
            modules=[{"id": "module-login", "name": "账户"}],
            functions=[{"id": "function-login", "module_id": "module-login", "name": "登录"}],
            linkages=[],
            test_points=[{"id": "point-login", "function_id": "function-login", "type": "positive", "description": "有效账号登录"}],
            coverage_report={"quality_reason": "存在少量证据待确认", "needs_confirmation": True},
            quality_status=RequirementAnalysis.QualityStatus.NEEDS_REVIEW,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_reviewable_analysis_is_confirmed_and_then_generates(self) -> None:
        response = self.client.post(
            f"/api/requirement-documents/{self.document.pk}/confirm-analysis/",
            {
                "reviewed_test_point_ids": ["point-login"],
                "reviewed_evidence_ids": [],
                "reviewed_analysis_item_ids": ["module-login", "function-login", "point-login"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.analysis.refresh_from_db()
        self.assertEqual(self.analysis.quality_status, RequirementAnalysis.QualityStatus.COMPLETE)
        self.assertFalse(self.analysis.coverage_report["needs_confirmation"])
        self.assertTrue(self.analysis.coverage_report["manual_confirmation"]["confirmed"])

        record = generate_document_cases(self.document, self.analysis)

        self.assertEqual(record.status, CaseGenerationRecord.Status.COMPLETED)
        self.assertTrue(record.cases)
        self.assertEqual(record.coverage_report["covered_test_point_ids"], ["point-login"])

    def test_selected_test_points_can_be_marked_reviewed_before_final_confirmation(self) -> None:
        response = self.client.post(
            f"/api/requirement-documents/{self.document.pk}/review-test-points/",
            {"reviewed_test_point_ids": ["point-login"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.analysis.refresh_from_db()
        self.assertEqual(self.analysis.quality_status, RequirementAnalysis.QualityStatus.NEEDS_REVIEW)
        self.assertEqual(
            self.analysis.coverage_report["manual_confirmation"]["reviewed_test_point_ids"],
            ["point-login"],
        )

        generated = self.client.post(
            "/api/case-generation/",
            {"document": str(self.document.pk), "reviewed_test_point_ids": ["point-login"]},
            format="json",
        )

        self.assertEqual(generated.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("正式用例生成", str(generated.data))

        confirmed = self.client.post(
            f"/api/requirement-documents/{self.document.pk}/confirm-analysis/",
            {
                "reviewed_test_point_ids": ["point-login"],
                "reviewed_evidence_ids": [],
                "reviewed_analysis_item_ids": ["module-login", "function-login", "point-login"],
            },
            format="json",
        )
        self.assertEqual(confirmed.status_code, status.HTTP_200_OK, confirmed.data)
        latest = confirmed.data["latest_analysis"]
        self.assertTrue(latest["analysis_complete"])
        self.assertEqual(latest["manual_review_status"], "confirmed")
        self.assertTrue(latest["manual_review_complete"])
        self.assertTrue(latest["generation_allowed"])

        generated = self.client.post(
            "/api/case-generation/",
            {"document": str(self.document.pk), "reviewed_test_point_ids": ["point-login"]},
            format="json",
        )

        self.assertEqual(generated.status_code, status.HTTP_201_CREATED)
        self.assertEqual(generated.data["coverage_report"]["reviewed_test_point_ids"], ["point-login"])
        self.assertTrue(generated.data["cases"])

    def test_review_test_points_requires_authentication_and_manager_access(self) -> None:
        self.client.force_authenticate(None)
        anonymous = self.client.post(
            f"/api/requirement-documents/{self.document.pk}/review-test-points/",
            {"reviewed_test_point_ids": ["point-login"]},
            format="json",
        )
        self.assertEqual(anonymous.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(self.viewer)
        viewer = self.client.post(
            f"/api/requirement-documents/{self.document.pk}/review-test-points/",
            {"reviewed_test_point_ids": ["point-login"]},
            format="json",
        )
        self.assertEqual(viewer.status_code, status.HTTP_403_FORBIDDEN)

    def test_reviewable_analysis_rejects_an_incomplete_checklist(self) -> None:
        response = self.client.post(
            f"/api/requirement-documents/{self.document.pk}/confirm-analysis/",
            {"reviewed_test_point_ids": ["point-login"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("审核未完成", str(response.data))

    def test_complete_analysis_keeps_manual_confirmation_selection(self) -> None:
        self.analysis.modules = [{"id": "module-login", "name": "账户", "evidence_ids": ["e1"]}]
        self.analysis.functions = [{"id": "function-login", "module_id": "module-login", "name": "登录", "evidence_ids": ["e1"]}]
        self.analysis.test_points = [
            {"id": "point-login", "function_id": "function-login", "type": "positive", "description": "有效账号登录", "evidence_ids": ["e1"]},
            {"id": "point-password", "function_id": "function-login", "type": "negative", "description": "错误密码拒绝", "evidence_ids": ["e1"]},
        ]
        self.analysis.quality_status = RequirementAnalysis.QualityStatus.COMPLETE
        self.analysis.coverage_report = {"needs_confirmation": False}
        self.analysis.save(update_fields=("modules", "functions", "test_points", "quality_status", "coverage_report"))

        selected = self.client.post(
            f"/api/requirement-documents/{self.document.pk}/review-test-points/",
            {"reviewed_test_point_ids": ["point-login"]},
            format="json",
        )

        self.assertEqual(selected.status_code, status.HTTP_200_OK)
        self.analysis.refresh_from_db()
        self.assertEqual(
            self.analysis.coverage_report["manual_confirmation"]["reviewed_test_point_ids"],
            ["point-login"],
        )

        confirmed = self.client.post(
            f"/api/requirement-documents/{self.document.pk}/confirm-analysis/",
            {
                "reviewed_test_point_ids": ["point-login", "point-password"],
                "reviewed_evidence_ids": [],
                "reviewed_analysis_item_ids": [],
            },
            format="json",
        )

        self.assertEqual(confirmed.status_code, status.HTTP_200_OK, confirmed.data)
        self.analysis.refresh_from_db()
        self.assertEqual(
            self.analysis.coverage_report["manual_confirmation"]["reviewed_test_point_ids"],
            ["point-login", "point-password"],
        )

    def test_partial_analysis_cannot_be_confirmed(self) -> None:
        self.analysis.quality_status = RequirementAnalysis.QualityStatus.PARTIAL
        self.analysis.save(update_fields=("quality_status",))

        response = self.client.post(f"/api/requirement-documents/{self.document.pk}/confirm-analysis/", format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.analysis.refresh_from_db()
        self.assertEqual(self.analysis.quality_status, RequirementAnalysis.QualityStatus.PARTIAL)

    def test_broken_test_point_mapping_cannot_be_confirmed(self) -> None:
        self.analysis.test_points = [{"id": "point-login", "type": "positive", "description": "有效账号登录"}]
        self.analysis.save(update_fields=("test_points",))

        response = self.client.post(
            f"/api/requirement-documents/{self.document.pk}/confirm-analysis/",
            {
                "reviewed_test_point_ids": ["point-login"],
                "reviewed_evidence_ids": [],
                "reviewed_analysis_item_ids": ["module-login", "function-login", "point-login"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("不能确认", str(response.data))
        self.analysis.refresh_from_db()
        self.assertEqual(self.analysis.quality_status, RequirementAnalysis.QualityStatus.NEEDS_REVIEW)
