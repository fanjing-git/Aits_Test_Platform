"""API tests for the T095 case-generation workbench."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.case_generation.models import CaseGenerationRecord
from apps.projects.models import Project, ProjectMember
from apps.requirement_analysis.analyzer import analyze_requirement_document
from apps.requirement_analysis.models import RequirementDocument
from apps.users.models import UserProfile


class CaseGenerationApiTests(TestCase):
    """Verify generation, review, selection and project isolation."""

    def setUp(self) -> None:
        User = get_user_model()
        self.owner = User.objects.create_user(username="t095-owner")
        self.viewer = User.objects.create_user(username="t095-viewer")
        self.outsider = User.objects.create_user(username="t095-outsider")
        self.owner.profile.role = UserProfile.Role.TEST_LEADER
        self.owner.profile.save(update_fields=("role",))
        self.project = Project.objects.create(name="T095 project", created_by=self.owner)
        ProjectMember.objects.create(project=self.project, user=self.viewer, role=ProjectMember.Role.VIEWER)
        self.document = RequirementDocument.objects.create(project=self.project, title="登录", content_text="用户登录系统。", created_by=self.owner)
        analysis = analyze_requirement_document(self.document)
        analysis.coverage_report = {**analysis.coverage_report, "manual_confirmation": {"confirmed": True}}
        analysis.save(update_fields=("coverage_report",))
        self.url = "/api/case-generation/"
        self.client = APIClient()

    def test_owner_can_generate_review_and_select(self) -> None:
        self.client.force_authenticate(self.owner)
        created = self.client.post(self.url, {"document": str(self.document.pk)}, format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        record_id = created.data["id"]
        self.assertGreater(created.data["total_cases"], 0)
        self.assertEqual(created.data["skill_execution"]["status"], "completed")
        reviewed = self.client.post(f"{self.url}{record_id}/review/")
        self.assertEqual(reviewed.status_code, status.HTTP_200_OK)
        self.assertEqual(reviewed.data["skill_execution"]["status"], "completed")
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

    def test_owner_can_save_manual_review_corrections_and_additions(self) -> None:
        self.client.force_authenticate(self.owner)
        created = self.client.post(self.url, {"document": str(self.document.pk)}, format="json")
        record_id = created.data["id"]
        reviewed = self.client.post(f"{self.url}{record_id}/review/")
        self.assertEqual(reviewed.status_code, status.HTTP_200_OK)
        original_case = reviewed.data["cases"][0]
        response = self.client.post(
            f"{self.url}{record_id}/review-cases/",
            {
                "cases": [{
                    "id": original_case["id"],
                    "expected_result": "人工确认后的登录结果",
                    "steps": ["输入有效账号和密码", "点击登录", "核对登录结果"],
                }],
                "new_cases": [{
                    "title": "人工补充登录失败提示",
                    "steps": ["输入错误密码", "点击登录"],
                    "expected_result": "页面显示明确的错误提示且不创建登录会话",
                    "type": "negative",
                    "test_design_method": "error_guessing",
                }],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_cases"], created.data["total_cases"] + 1)
        self.assertEqual(response.data["review_rounds"], 0)
        self.assertEqual(response.data["review_report"]["manual_revision"]["status"], "saved_pending_review")
        corrected = next(item for item in response.data["cases"] if item["id"] == original_case["id"])
        self.assertEqual(corrected["expected_result"], "人工确认后的登录结果")
        self.assertEqual(corrected["manual_review_status"], "manual_final")
        self.assertEqual(corrected["manual_revision_label"], "人工修订用例")
        self.assertTrue(any(item.get("manual_added") for item in response.data["cases"]))

    def test_manual_revision_persists_function_linkage_and_invalidates_selection(self) -> None:
        analysis = self.document.analyses.order_by("-created_at").first()
        primary_function = dict(analysis.functions[0])
        alternate_function = {
            "id": "manual-review-function",
            "module_id": primary_function.get("module_id"),
            "name": "人工审核功能点",
            "description": "用于验证人工修订关联范围",
            "evidence_ids": primary_function.get("evidence_ids", []),
        }
        analysis.functions = [primary_function, alternate_function]
        analysis.save(update_fields=("functions",))
        self.client.force_authenticate(self.owner)
        created = self.client.post(self.url, {"document": str(self.document.pk)}, format="json")
        record_id = created.data["id"]
        reviewed = self.client.post(f"{self.url}{record_id}/review/")
        selected = self.client.post(f"{self.url}{record_id}/select/")
        self.assertEqual(selected.status_code, status.HTTP_200_OK)
        original_case = reviewed.data["cases"][0]

        response = self.client.post(
            f"{self.url}{record_id}/review-cases/",
            {"cases": [{"id": original_case["id"], "source_function_id": alternate_function["id"]}]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        corrected = next(item for item in response.data["cases"] if item["id"] == original_case["id"])
        self.assertEqual(corrected["source_function_id"], alternate_function["id"])
        self.assertEqual(corrected["source_module_id"], alternate_function["module_id"])
        self.assertNotIn("automation_selection", response.data["coverage_report"])
        self.assertEqual(response.data["coverage_report"]["automation_selection_invalidated"]["reason"], "manual_revision")
        self.assertEqual(len(response.data["coverage_report"]["automation_selection_invalidation_history"]), 1)

    def test_manual_revision_rejects_function_outside_analysis_scope(self) -> None:
        self.client.force_authenticate(self.owner)
        created = self.client.post(self.url, {"document": str(self.document.pk)}, format="json")
        record_id = created.data["id"]
        reviewed = self.client.post(f"{self.url}{record_id}/review/")
        original_case = reviewed.data["cases"][0]

        response = self.client.post(
            f"{self.url}{record_id}/review-cases/",
            {"cases": [{"id": original_case["id"], "source_function_id": "not-in-analysis"}]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("不属于当前需求分析结果", response.data["detail"])

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
        self.assertEqual(issue["severity_label"], "中")
        self.assertTrue(issue["id"])

    def test_review_issue_ids_are_stable_when_legacy_records_are_missing_or_duplicated(self) -> None:
        record = CaseGenerationRecord.objects.create(
            project=self.project,
            document=self.document,
            cases=[{"id": "case-001", "title": "登录", "type": "positive", "steps": ["执行"], "expected_result": "成功"}],
            review_rounds=5,
            review_report={"approved": False, "issues": [
                {"id": "same", "severity": "high", "description": "问题一", "suggestion": "建议一"},
                {"id": "same", "severity": "low", "description": "问题二", "suggestion": "建议二"},
                {"severity": "medium", "description": "问题三", "suggestion": "建议三"},
            ]},
        )
        self.client.force_authenticate(self.owner)
        response = self.client.get(f"{self.url}{record.id}/")
        ids = [item["id"] for item in response.data["review_report"]["issues"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([item["severity_label"] for item in response.data["review_report"]["issues"]], ["高", "低", "中"])

    def test_viewer_reads_but_cannot_mutate_and_outsider_is_hidden(self) -> None:
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(self.url, {"document": str(self.document.pk)}, format="json").status_code, status.HTTP_201_CREATED)
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.post(self.url, {"document": str(self.document.pk)}, format="json").status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.url).data, [])

    def test_owner_can_delete_generation_record_without_deleting_document(self) -> None:
        record = CaseGenerationRecord.objects.create(
            project=self.project,
            document=self.document,
            total_cases=1,
            cases=[{"id": "case-001"}],
        )
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.delete(f"{self.url}{record.id}/").status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(self.owner)
        response = self.client.delete(f"{self.url}{record.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(CaseGenerationRecord.objects.filter(pk=record.id).exists())
        self.assertTrue(RequirementDocument.objects.filter(pk=self.document.id).exists())

    def test_empty_record_review_is_skipped_and_not_left_reviewing(self) -> None:
        record = CaseGenerationRecord.objects.create(
            project=self.project,
            document=self.document,
            status=CaseGenerationRecord.Status.REVIEWING,
            cases=[],
        )
        self.client.force_authenticate(self.owner)
        response = self.client.post(f"{self.url}{record.id}/review/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], CaseGenerationRecord.Status.COMPLETED)
        self.assertEqual(response.data["review_report"]["execution_status"], "skipped")
        self.assertEqual(response.data["review_report"]["message"], "当前记录没有可评审的用例。")
        record.refresh_from_db()
        self.assertEqual(record.status, CaseGenerationRecord.Status.COMPLETED)

    def test_empty_generation_shell_is_exposed_as_not_generated(self) -> None:
        record = CaseGenerationRecord.objects.create(
            project=self.project,
            document=self.document,
            status=CaseGenerationRecord.Status.GENERATING,
            rounds=0,
            total_cases=0,
            cases=[],
            coverage_report={},
            review_report={},
        )
        self.client.force_authenticate(self.owner)
        response = self.client.get(f"{self.url}{record.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], CaseGenerationRecord.Status.FAILED)
        self.assertEqual(response.data["coverage_report"]["message"], "本次没有生成任何用例，请重新生成。")
        self.assertEqual(response.data["review_report"]["message"], "本次没有生成任何用例，暂无用例可评审。")

    def test_active_empty_generation_is_kept_generating(self) -> None:
        record = CaseGenerationRecord.objects.create(
            project=self.project,
            document=self.document,
            status=CaseGenerationRecord.Status.GENERATING,
            rounds=0,
            total_cases=0,
            cases=[],
            coverage_report={
                "generation_status": "generating",
                "execution_status": "running",
                "reviewed_test_point_ids": ["point-1"],
            },
            review_report={},
        )
        self.client.force_authenticate(self.owner)
        response = self.client.get(f"{self.url}{record.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], CaseGenerationRecord.Status.GENERATING)
        self.assertEqual(response.data["coverage_report"]["execution_status"], "running")

    def test_generation_requires_completed_analysis_and_login(self) -> None:
        pending = RequirementDocument.objects.create(project=self.project, title="未分析", content_text="内容", created_by=self.owner)
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.url, {"document": str(pending.pk)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_generation_rejects_analysis_needing_review(self) -> None:
        analysis = self.document.analyses.order_by("-created_at").first()
        analysis.quality_status = "needs_review"
        analysis.coverage_report = {**analysis.coverage_report, "analysis_method": "model_verified"}
        analysis.save(update_fields=("quality_status", "coverage_report"))
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.url, {"document": str(self.document.pk)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_generation_rejects_complete_analysis_without_manual_confirmation(self) -> None:
        analysis = self.document.analyses.order_by("-created_at").first()
        analysis.coverage_report = {**analysis.coverage_report, "manual_confirmation": {"confirmed": False}}
        analysis.save(update_fields=("coverage_report",))
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.url, {"document": str(self.document.pk)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("人工审核尚未完成", str(response.data))

    def test_model_options_filter_generation_and_review_capabilities(self) -> None:
        from apps.configs.models import ModelConfig

        chat = ModelConfig.objects.create(name="case-options-chat", provider=ModelConfig.Provider.CUSTOM, model_name="chat", model_type=ModelConfig.ModelType.CHAT)
        ModelConfig.objects.create(name="case-options-embedding", provider=ModelConfig.Provider.CUSTOM, model_name="embedding", model_type=ModelConfig.ModelType.EMBEDDING)
        self.client.force_authenticate(self.owner)
        generation = self.client.get(f"{self.url}model-options/?feature=case_generation")
        review = self.client.get(f"{self.url}model-options/?feature=case_review")
        self.assertEqual(generation.status_code, status.HTTP_200_OK)
        self.assertEqual(review.status_code, status.HTTP_200_OK)
        self.assertIn(chat.id, [item["id"] for item in generation.data["models"]])
        self.assertNotIn("case-options-embedding", [item["name"] for item in generation.data["models"]])
        self.assertEqual(generation.data["feature_key"], "case_generation")
