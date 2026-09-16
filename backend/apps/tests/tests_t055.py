"""Focused tests for the T055 test execution persistence models."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase as DjangoTestCase

from apps.environments.models import Environment
from apps.projects.models import Project
from apps.tests.models import Evaluation, TestCase, TestResult, TestRun


class TestExecutionModelsTests(DjangoTestCase):
    """Verify model defaults, automation labels, and project isolation."""

    def setUp(self) -> None:
        """Create two isolated projects and their test environments."""
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="t055-owner", password="safe-test-password")
        self.project = Project.objects.create(name="T055 Project", created_by=self.owner)
        self.other_project = Project.objects.create(name="T055 Other", created_by=self.owner)
        self.environment = Environment.objects.create(
            project=self.project,
            name=Environment.Name.TEST,
            base_url="https://test.example.com",
        )
        self.other_environment = Environment.objects.create(
            project=self.other_project,
            name=Environment.Name.TEST,
            base_url="https://other.example.com",
        )

    def make_case(self, project: Project | None = None, case_id: str = "TC-T055-001") -> TestCase:
        """Create a valid API test case for model-level assertions."""
        case = TestCase(
            project=project or self.project,
            case_id=case_id,
            title="创建测试执行记录",
            steps=[{"method": "POST", "path": "/api/test-runs/"}],
            input_data={"name": "smoke"},
            expected_result="返回成功状态。",
            case_type=TestCase.CaseType.API,
            is_automation=True,
            automation_difficulty=TestCase.AutomationDifficulty.LOW,
            automation_tech=TestCase.AutomationTech.PYTEST,
            requirement_mapping={"task": "T055"},
        )
        case.full_clean()
        case.save()
        return case

    def test_automation_metadata_and_defaults_are_persisted(self) -> None:
        """Automation labels and JSON defaults should survive persistence."""
        case = self.make_case()
        run = TestRun.objects.create(
            project=self.project,
            environment=self.environment,
            name="T055 smoke run",
            created_by=self.owner,
        )
        run.attach_test_cases(case)
        result = TestResult.objects.create(run=run, test_case=case, status=TestResult.Status.PASSED)
        evaluation = Evaluation.objects.create(run=run, result=result, score=100, grade="A")

        self.assertEqual(case.automation_tech, TestCase.AutomationTech.PYTEST)
        self.assertEqual(run.test_cases.get(), case)
        self.assertEqual(result.assertions, [])
        self.assertEqual(evaluation.recommendations, [])

    def test_automation_case_requires_planning_labels(self) -> None:
        """An automated case cannot omit difficulty or technology metadata."""
        case = TestCase(
            project=self.project,
            case_id="TC-T055-002",
            title="缺少自动化标注",
            expected_result="校验失败。",
            is_automation=True,
        )
        with self.assertRaises(ValidationError) as context:
            case.full_clean()
        self.assertIn("automation_difficulty", context.exception.message_dict)
        self.assertIn("automation_tech", context.exception.message_dict)

    def test_run_environment_and_case_attachment_are_project_scoped(self) -> None:
        """Runs must not cross project boundaries through environment or M2M links."""
        other_case = self.make_case(self.other_project, "TC-T055-003")
        run = TestRun(project=self.project, environment=self.other_environment, name="非法环境")
        with self.assertRaises(ValidationError):
            run.full_clean()

        run.environment = self.environment
        run.full_clean()
        run.save()
        with self.assertRaises(ValidationError):
            run.attach_test_cases(other_case)

    def test_result_and_evaluation_cannot_cross_run_or_project(self) -> None:
        """Result and evaluation associations must remain internally consistent."""
        case = self.make_case()
        other_case = self.make_case(self.other_project, "TC-T055-004")
        run = TestRun.objects.create(project=self.project, name="主执行")
        other_run = TestRun.objects.create(project=self.other_project, name="其他执行")

        result = TestResult(run=run, test_case=other_case)
        with self.assertRaises(ValidationError):
            result.full_clean()

        other_result = TestResult.objects.create(run=other_run, test_case=other_case)
        evaluation = Evaluation(run=run, result=other_result)
        with self.assertRaises(ValidationError):
            evaluation.full_clean()

        valid_result = TestResult(run=run, test_case=case)
        valid_result.full_clean()
