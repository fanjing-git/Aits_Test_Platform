"""Focused T155C five-round orchestration and REST progress tests."""

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.projects.models import Project
from apps.requirement_analysis.llm_adapter import ModelAnalysisError
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument
from apps.requirement_analysis.rounds import run_five_round_analysis
from apps.users.models import UserProfile


def payload(*, extra_test_point: bool = False) -> dict[str, object]:
    """Return an evidence-grounded model payload for one semantic round."""
    points = [{"id": "point-login", "function_id": "function-login", "type": "positive", "description": "验证用户登录", "evidence_ids": ["evidence-login"]}]
    if extra_test_point:
        points.append({"id": "point-retry", "function_id": "function-login", "type": "boundary", "description": "验证登录重试", "evidence_ids": ["evidence-login"]})
    return {
        "modules": [{"id": "module-account", "name": "账户", "evidence_ids": ["evidence-login"]}],
        "functions": [{"id": "function-login", "module_id": "module-account", "name": "登录", "description": "用户登录", "evidence_ids": ["evidence-login"]}],
        "linkages": [],
        "test_points": points,
        "coverage_report": {"structured_generation": {"status": "completed", "segment_count": 1, "completed_segments": 1, "segments": [{"segment_id": "segment-0001", "status": "completed"}]}},
    }


class FakeRoundAdapter:
    """Small injected adapter that records semantic prompts without networking."""

    def __init__(self, *, fail_round: int | None = None) -> None:
        self.calls = 0
        self.fail_round = fail_round
        self.prompts: list[str] = []

    def analyze(self, **kwargs):
        self.calls += 1
        self.prompts.append(str(kwargs.get("prompt_override") or ""))
        if self.fail_round == self.calls:
            raise ModelAnalysisError(
                "模型暂时不可用",
                code="provider_timeout",
                structured_trace=[{"segment_id": "segment-0001", "status": "failed", "error_code": "provider_timeout"}],
                partial_payload={"coverage_report": {"structured_generation": {"status": "failed", "segment_count": 1, "completed_segments": 0}}},
            )
        return payload(extra_test_point=self.calls == 3)


class ConflictRoundAdapter(FakeRoundAdapter):
    """Return the same model ID with changed semantics to exercise conflict tracking."""

    def analyze(self, **kwargs):
        result = super().analyze(**kwargs)
        if self.calls == 2:
            result["modules"][0]["name"] = "账户（修订）"
        return result


class FieldConflictRoundAdapter(FakeRoundAdapter):
    """Change a field under the same semantic key to catch silent overwrites."""

    def analyze(self, **kwargs):
        result = super().analyze(**kwargs)
        if self.calls == 2:
            result["functions"][0]["description"] = "改写后的登录说明"
        return result


class RequirementRoundsT155CTests(SimpleTestCase):
    """Verify semantic rounds are distinct from inner segments and recoverable."""

    def test_runs_five_rounds_and_merges_duplicates(self) -> None:
        adapter = FakeRoundAdapter()
        result = run_five_round_analysis(
            text="用户登录系统。",
            evidence=[{"id": "evidence-login", "text": "用户登录系统。"}],
            adapter=adapter,
        )

        self.assertEqual(adapter.calls, 5)
        self.assertEqual(result["coverage_report"]["round_count"], 5)
        self.assertEqual(result["coverage_report"]["completed_rounds"], 5)
        self.assertEqual(result["coverage_report"]["round_execution_status"], "completed")
        self.assertEqual(len(result["coverage_report"]["rounds"]), 5)
        self.assertGreater(result["coverage_report"]["rounds"][1]["duplicate"], 0)
        self.assertEqual(len(result["test_points"]), 2)
        self.assertIn("modules、functions、linkages、test_points、coverage_report 五个字段", adapter.prompts[0])
        self.assertIn("必须始终是对象数组", adapter.prompts[0])

    def test_failure_keeps_partial_rounds_and_can_resume(self) -> None:
        failing = FakeRoundAdapter(fail_round=2)
        try:
            run_five_round_analysis(
                text="用户登录系统。",
                evidence=[{"id": "evidence-login", "text": "用户登录系统。"}],
                adapter=failing,
            )
        except ModelAnalysisError as exc:
            self.assertEqual(exc.code, "provider_timeout")
            partial = exc.partial_payload
        else:
            self.fail("expected a recoverable round failure")

        self.assertEqual(partial["coverage_report"]["completed_rounds"], 1)
        self.assertEqual(partial["coverage_report"]["rounds"][1]["status"], "failed")
        resumed = run_five_round_analysis(
            text="用户登录系统。",
            evidence=[{"id": "evidence-login", "text": "用户登录系统。"}],
            adapter=FakeRoundAdapter(),
            resume_round=2,
            prior_payload=partial,
            prior_rounds=partial["coverage_report"]["rounds"],
        )
        self.assertEqual(resumed["coverage_report"]["completed_rounds"], 5)
        self.assertEqual(resumed["coverage_report"]["round_progress"]["status"], "completed")

    def test_same_id_with_changed_semantics_is_recorded_as_conflict(self) -> None:
        result = run_five_round_analysis(
            text="用户登录系统。",
            evidence=[{"id": "evidence-login", "text": "用户登录系统。"}],
            adapter=ConflictRoundAdapter(),
        )

        self.assertGreaterEqual(len(result["coverage_report"]["conflicts"]), 1)
        self.assertGreaterEqual(result["coverage_report"]["rounds"][1]["conflict"], 1)

    def test_same_business_key_does_not_silently_overwrite_fields(self) -> None:
        result = run_five_round_analysis(
            text="用户登录系统。",
            evidence=[{"id": "evidence-login", "text": "用户登录系统。"}],
            adapter=FieldConflictRoundAdapter(),
        )

        function = next(item for item in result["functions"] if item["id"] == "function-login")
        self.assertEqual(function["description"], "用户登录")
        conflicts = result["coverage_report"]["conflicts"]
        self.assertTrue(any(item["reason"] == "same_business_key_different_fields" for item in conflicts))
        field_conflict = next(item for item in conflicts if item["reason"] == "same_business_key_different_fields")
        self.assertEqual(field_conflict["fields"][0]["field"], "description")
        self.assertEqual(field_conflict["fields"][0]["existing_value"], "用户登录")
        self.assertEqual(field_conflict["fields"][0]["incoming_value"], "改写后的登录说明")
        self.assertTrue(result["coverage_report"]["conflict_review"]["required"])
        self.assertIn(field_conflict["id"], result["coverage_report"]["conflict_review"]["pending_conflict_ids"])


class RequirementRoundsRestT155CTests(TestCase):
    """Verify progress/history and permission boundaries use the existing API scope."""

    def setUp(self) -> None:
        self.owner = get_user_model().objects.create_user(username="t155c-owner")
        self.viewer = get_user_model().objects.create_user(username="t155c-viewer")
        self.owner.profile.role = UserProfile.Role.TEST_LEADER
        self.owner.profile.save(update_fields=("role",))
        self.project = Project.objects.create(name="T155C project", created_by=self.owner)
        self.document = RequirementDocument.objects.create(
            project=self.project,
            title="登录需求",
            content_text="用户登录系统。",
            parse_evidence=[{"id": "evidence-login", "text": "用户登录系统。"}],
            created_by=self.owner,
        )
        self.analysis = RequirementAnalysis.objects.create(
            document=self.document,
            modules=[], functions=[], linkages=[], test_points=[],
            coverage_report={"round_count": 5, "completed_rounds": 2, "round_execution_status": "partial", "round_progress": {"current_round": 3, "total_rounds": 5, "status": "partial"}, "rounds": [{"round": 1, "name": "基础拆解", "status": "completed"}, {"round": 2, "name": "异常风险", "status": "failed"}]},
            quality_status=RequirementAnalysis.QualityStatus.PARTIAL,
        )
        self.client = APIClient()

    def test_progress_returns_rounds_and_history(self) -> None:
        self.client.force_authenticate(self.owner)
        response = self.client.get(f"/api/requirement-documents/{self.document.pk}/analysis-progress/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["round_progress"]["current_round"], 3)
        self.assertEqual(response.data["rounds"][1]["status"], "failed")
        self.assertEqual(len(response.data["history"]), 1)

    def test_progress_requires_project_visibility(self) -> None:
        self.client.force_authenticate(self.viewer)
        response = self.client.get(f"/api/requirement-documents/{self.document.pk}/analysis-progress/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_progress_requires_authentication(self) -> None:
        response = self.client.get(f"/api/requirement-documents/{self.document.pk}/analysis-progress/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_analyze_rejects_invalid_resume_round_before_model_call(self) -> None:
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            f"/api/requirement-documents/{self.document.pk}/analyze/",
            {"resume_round": 6},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("resume_round", response.data)

    def test_confirm_requires_merge_conflicts_to_be_reviewed(self) -> None:
        self.analysis.quality_status = RequirementAnalysis.QualityStatus.NEEDS_REVIEW
        self.analysis.coverage_report = {
            **self.analysis.coverage_report,
            "conflicts": [{"id": "conflict-r2-functions-1", "collection": "functions", "round": 2}],
        }
        self.analysis.save(update_fields=("quality_status", "coverage_report"))
        self.client.force_authenticate(self.owner)

        blocked = self.client.post(
            f"/api/requirement-documents/{self.document.pk}/confirm-analysis/",
            {"reviewed_conflict_ids": []},
            format="json",
        )
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("合并冲突", blocked.data["detail"])

        confirmed = self.client.post(
            f"/api/requirement-documents/{self.document.pk}/confirm-analysis/",
            {"reviewed_conflict_ids": ["conflict-r2-functions-1"]},
            format="json",
        )
        self.assertEqual(confirmed.status_code, status.HTTP_200_OK)
        self.analysis.refresh_from_db()
        self.assertEqual(
            self.analysis.coverage_report["manual_confirmation"]["reviewed_conflict_ids"],
            ["conflict-r2-functions-1"],
        )
        self.assertEqual(self.analysis.coverage_report["conflict_review"]["status"], "resolved")
