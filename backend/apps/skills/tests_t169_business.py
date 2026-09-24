"""Business-entry tests for T169 real Service parent runs."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.case_generation.models import CaseGenerationRecord
from apps.projects.models import Project
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument
from apps.skills.models import SkillChainRun
from apps.users.models import UserProfile


class BusinessSkillParentRunTests(TestCase):
    """Verify business buttons persist artifacts and real parent-run evidence."""

    def setUp(self) -> None:
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="t169-business-owner", password="Admin123456!")
        self.owner.profile.role = UserProfile.Role.TEST_LEADER
        self.owner.profile.save(update_fields=("role",))
        self.project = Project.objects.create(name="T169 business project", created_by=self.owner)
        self.document = RequirementDocument.objects.create(
            project=self.project,
            title="业务父运行需求",
            version="2.1",
            content_text="用户可以登录系统。",
            created_by=self.owner,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("apps.requirement_analysis.views.analyze_requirement_document")
    def test_requirement_entry_uses_real_service_and_persists_parent_artifact(self, analyze) -> None:
        """The requirement button no longer reports a planning-only Skill result."""
        analysis = RequirementAnalysis(
            document=self.document,
            modules=[{"id": "m1", "name": "账户"}],
            functions=[{"id": "f1", "module_id": "m1", "name": "登录"}],
            linkages=[],
            test_points=[{"id": "p1", "function_id": "f1", "description": "登录成功"}],
            coverage_report={"round_count": 5},
            quality_status=RequirementAnalysis.QualityStatus.COMPLETE,
        )

        def persist(*args, **kwargs):
            analysis.save()
            return analysis

        analyze.side_effect = persist
        response = self.client.post(f"/api/requirement-documents/{self.document.pk}/analyze/", {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        document = RequirementDocument.objects.get(pk=self.document.pk)
        self.assertIsNotNone(document.analysis_run_id)
        run = SkillChainRun.objects.get(pk=document.analysis_run_id)
        self.assertEqual(run.status, SkillChainRun.Status.COMPLETED)
        self.assertEqual(run.execution_snapshot["runtime_kind"], "business_service")
        self.assertEqual(run.output_snapshot["artifact"]["type"], "requirement_analysis")
        self.assertEqual(response.data["skill_execution"]["runtime"], "business_service")
        self.assertEqual(response.data["skill_execution"]["run_id"], str(run.pk))
        analyze.assert_called_once()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    @patch("apps.requirement_analysis.views.run_requirement_analysis.apply_async")
    def test_queued_requirement_entry_links_pending_parent_run(self, apply_async) -> None:
        """The queued path passes the parent run id to the real worker task."""
        response = self.client.post(f"/api/requirement-documents/{self.document.pk}/analyze/", {}, format="json")

        self.assertEqual(response.status_code, 202, response.data)
        run = SkillChainRun.objects.get(pk=response.data["skill_execution"]["run_id"])
        self.assertEqual(run.status, SkillChainRun.Status.PENDING)
        self.assertEqual(run.execution_snapshot["business_ref"]["id"], str(self.document.pk))
        self.assertEqual(apply_async.call_args.kwargs["args"][-1], str(run.pk))

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("apps.case_generation.views.generate_document_cases")
    def test_case_generation_entry_persists_generation_parent_after_artifact(self, generate) -> None:
        """Case generation links its durable record to a completed business run."""
        analysis = RequirementAnalysis.objects.create(
            document=self.document,
            modules=[{"id": "m1", "name": "账户"}],
            functions=[{"id": "f1", "module_id": "m1", "name": "登录"}],
            linkages=[],
            test_points=[{"id": "p1", "function_id": "f1", "description": "登录成功"}],
            coverage_report={"manual_confirmation": {"confirmed": True, "reviewed_test_point_ids": ["p1"]}},
            quality_status=RequirementAnalysis.QualityStatus.COMPLETE,
        )
        def persist(*args, **kwargs):
            record = kwargs["record"]
            record.rounds = 5
            record.total_cases = 1
            record.auto_cases = 1
            record.manual_cases = 0
            record.cases = [{"id": "case-1", "title": "登录成功"}]
            record.coverage_report = {"execution_status": "completed"}
            record.status = CaseGenerationRecord.Status.COMPLETED
            record.save()
            return record

        generate.side_effect = persist
        response = self.client.post(
            "/api/case-generation/",
            {"document": str(self.document.pk), "reviewed_test_point_ids": ["p1"]},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        saved = CaseGenerationRecord.objects.get(document=self.document)
        self.assertIsNotNone(saved.generation_run_id)
        run = SkillChainRun.objects.get(pk=saved.generation_run_id)
        self.assertEqual(run.status, SkillChainRun.Status.COMPLETED)
        self.assertEqual(run.output_snapshot["artifact"]["id"], str(saved.pk))
        self.assertEqual(response.data["skill_execution"]["runtime"], "business_service")
        generate.assert_called_once()
