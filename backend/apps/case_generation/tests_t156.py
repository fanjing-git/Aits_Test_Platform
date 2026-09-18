"""Focused tests for the T156 generation/review execution contract."""
import json
from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.case_generation.generator import CaseGenerationError, generate_cases, generate_document_cases
from apps.case_generation.llm_adapter import CaseGenerationModelAdapter, _json_scope_segments
from apps.case_generation.models import CaseGenerationRecord
from apps.case_generation.reviewer import CaseReviewError, review_cases, review_generation_record
from apps.configs.models import ModelConfig, ModelRoutingPolicy
from apps.projects.models import Project
from apps.requirement_analysis.analyzer import analyze_requirement_document
from apps.requirement_analysis.llm_adapter import ModelAnalysisError
from apps.requirement_analysis.models import RequirementDocument


def _generation_payload() -> dict:
    """Return a minimal evidence-grounded analysis payload."""
    return {
        "modules": [{"id": "module-1", "name": "账户"}],
        "functions": [{"id": "function-1", "module_id": "module-1", "name": "登录"}],
        "test_points": [{"id": "point-1", "function_id": "function-1", "description": "登录校验"}],
        "linkages": [],
    }


class T156GenerationTests(SimpleTestCase):
    """Verify generation round states and safe downgrade semantics."""

    def _adapter(self, responses):
        adapter = CaseGenerationModelAdapter.__new__(CaseGenerationModelAdapter)
        adapter.adapter = Mock()
        adapter.adapter.run.side_effect = responses
        return adapter

    @staticmethod
    def _model_response(index: int) -> dict:
        return {
            "cases": [{
                "source_function_id": "function-1",
                "type": "positive",
                "title": f"登录场景 {index}",
                "steps": [f"执行登录 {index}"],
                "expected_result": "登录成功",
            }],
            "coverage_report": {
                "model_route": {"available": True, "effective_source": "feature", "model": {"name": "fake"}},
                "structured_generation": {"status": "completed", "segments": []},
            },
        }

    def test_every_model_round_is_recorded_with_actual_route(self):
        adapter = self._adapter([self._model_response(index) for index in range(1, 6)])
        result = generate_cases(_generation_payload(), model_adapter=adapter, document_text="登录需求")
        self.assertEqual(adapter.adapter.run.call_count, 5)
        self.assertEqual(result.coverage_report["analysis_method"], "model_verified")
        self.assertEqual([item["model_status"] for item in result.round_trace], ["completed"] * 5)
        self.assertEqual([item["model_route"]["model"]["name"] for item in result.round_trace], ["fake"] * 5)

    def test_explicit_test_point_and_design_method_are_stable_across_model_rephrasing(self):
        responses = []
        for index in range(1, 6):
            responses.append({
                "cases": [{
                    "source_function_id": "function-1",
                    "source_test_point_id": "point-1",
                    "type": "positive",
                    "test_design_method": "equivalence_class",
                    "scenario_key": "valid-login",
                    "title": f"登录场景改写 {index}",
                    "steps": [f"第 {index} 次执行登录"],
                    "expected_result": "登录成功",
                }],
            })

        result = generate_cases(_generation_payload(), model_adapter=self._adapter(responses))
        rerun = generate_cases(_generation_payload(), model_adapter=self._adapter(responses))

        self.assertEqual(result.coverage_report["case_count"], 5)
        self.assertEqual(rerun.coverage_report["case_count"], result.coverage_report["case_count"])
        self.assertEqual(
            sum(item["test_design_method"] == "equivalence_class" for item in result.cases),
            1,
        )
        self.assertEqual(
            len({(item["source_test_point_id"], item["test_design_method"]) for item in result.cases}),
            len(result.cases),
        )
        self.assertEqual(
            result.coverage_report["deduplication"]["strategy"],
            "source_test_point_id + test_design_method + scenario_key",
        )

    def test_same_test_point_and_method_keeps_distinct_stable_scenarios(self):
        responses = [{
            "cases": [
                {
                    "source_function_id": "function-1",
                    "source_test_point_id": "point-1",
                    "type": "positive",
                    "test_design_method": "equivalence_class",
                    "scenario_key": "valid-login",
                    "title": "有效账号登录",
                    "steps": ["输入有效账号"],
                    "expected_result": "登录成功",
                },
                {
                    "source_function_id": "function-1",
                    "source_test_point_id": "point-1",
                    "type": "positive",
                    "test_design_method": "equivalence_class",
                    "scenario_key": "valid-login-without-password",
                    "title": "缺少密码登录",
                    "steps": ["仅输入账号"],
                    "expected_result": "提示密码必填",
                },
            ],
        }] * 5

        result = generate_cases(_generation_payload(), model_adapter=self._adapter(responses))

        equivalence_cases = [item for item in result.cases if item["test_design_method"] == "equivalence_class"]
        self.assertEqual(len(equivalence_cases), 2)
        self.assertEqual({item["scenario_key"] for item in equivalence_cases}, {"valid-login", "valid-login-without-password"})

    def test_model_failure_round_is_not_omitted_or_marked_verified(self):
        failure = ModelAnalysisError("provider unavailable", code="provider_unavailable")
        adapter = self._adapter([self._model_response(1), failure, self._model_response(3)])
        with self.assertRaises(CaseGenerationError) as context:
            generate_cases(_generation_payload(), model_adapter=adapter, allow_deterministic_baseline=False)
        trace = context.exception.partial_round_trace
        self.assertEqual(len(trace), 2)
        self.assertEqual(trace[-1]["status"], "failed")
        self.assertEqual(trace[-1]["error_code"], "provider_unavailable")

    def test_explicit_deterministic_fallback_has_distinct_method(self):
        failure = ModelAnalysisError("provider unavailable", code="provider_unavailable")
        adapter = self._adapter([self._model_response(1), failure, self._model_response(3), self._model_response(4), self._model_response(5)])
        result = generate_cases(_generation_payload(), model_adapter=adapter, allow_deterministic_baseline=True)
        self.assertEqual(result.coverage_report["analysis_method"], "deterministic_fallback")
        self.assertNotEqual(result.coverage_report["analysis_method"], "model_verified")
        self.assertEqual(result.round_trace[1]["model_status"], "failed")

    def test_deterministic_generation_uses_test_points_as_minimum_unit(self):
        payload = {
            "modules": [{"id": "module-1", "name": "账户"}],
            "functions": [{"id": "function-1", "module_id": "module-1", "name": "登录"}],
            "test_points": [
                {"id": "point-positive", "function_id": "function-1", "type": "positive", "description": "有效账号登录"},
                {"id": "point-negative", "function_id": "function-1", "type": "negative", "description": "错误密码拒绝"},
                {"id": "point-boundary", "function_id": "function-1", "type": "boundary", "description": "密码长度边界"},
            ],
            "linkages": [],
        }

        result = generate_cases(payload)

        self.assertEqual(result.coverage_report["test_point_count"], 3)
        self.assertEqual(result.coverage_report["covered_test_point_ids"], ["point-boundary", "point-negative", "point-positive"])
        self.assertEqual(result.coverage_report["test_point_coverage_rate"], 1.0)
        self.assertTrue(all(item["source_test_point_id"] for item in result.cases))
        self.assertTrue(any("有效账号登录" in item["title"] for item in result.cases))

    def test_generation_can_be_limited_to_reviewed_test_points(self):
        payload = {
            **_generation_payload(),
            "test_points": [
                {"id": "point-positive", "function_id": "function-1", "type": "positive", "description": "有效账号登录"},
                {"id": "point-negative", "function_id": "function-1", "type": "negative", "description": "错误密码拒绝"},
            ],
        }

        result = generate_cases(payload, test_point_ids=["point-negative"])

        self.assertEqual(result.coverage_report["test_point_count"], 1)
        self.assertEqual(result.coverage_report["covered_test_point_ids"], ["point-negative"])

    def test_dynamic_coverage_plan_reports_required_dimensions_without_case_cap(self):
        payload = {
            **_generation_payload(),
            "test_points": [
                {
                    "id": "point-boundary",
                    "function_id": "function-1",
                    "type": "boundary",
                    "description": "密码长度上限和下限校验",
                },
                {
                    "id": "point-security",
                    "function_id": "function-1",
                    "type": "security",
                    "description": "未授权访问拒绝",
                },
            ],
        }

        result = generate_cases(payload)

        plan = {item["test_point_id"]: set(item["required_design_methods"]) for item in result.coverage_report["coverage_plan"]}
        self.assertIn("boundary_value", plan["point-boundary"])
        self.assertIn("equivalence_class", plan["point-boundary"])
        self.assertEqual(plan["point-security"], {"error_guessing", "security"})
        self.assertEqual(result.coverage_report["coverage_gaps"], [])

    def test_review_segments_bound_unreferenced_evidence_and_case_batch_size(self):
        scope = {
            "requirement": "需求" * 100,
            "cases": [{"id": f"case-{index:03d}", "title": f"用例{index}"} for index in range(25)],
            "existing_issues": [],
            "existing_corrections": [],
        }
        evidence = [{"id": f"paragraph-{index}", "text": "证据" * 100} for index in range(142)]

        segments = _json_scope_segments(
            json.dumps(scope, ensure_ascii=False),
            evidence,
            24000,
            32,
            collection_key="cases",
            unreferenced_evidence_limit=8,
            max_collection_items=12,
        )

        self.assertEqual([len(json.loads(item.text)["cases"]) for item in segments], [12, 12, 1])
        self.assertEqual([len(item.evidence) for item in segments], [8, 8, 8])

    def test_selected_scope_only_sends_related_functions_to_model(self):
        payload = {
            "modules": [{"id": "module-1", "name": "账户"}, {"id": "module-2", "name": "订单"}],
            "functions": [
                {"id": "function-1", "module_id": "module-1", "name": "登录"},
                {"id": "function-2", "module_id": "module-2", "name": "下单"},
            ],
            "test_points": [
                {"id": "point-1", "function_id": "function-1", "description": "登录校验"},
                {"id": "point-2", "function_id": "function-2", "description": "下单校验"},
            ],
            "linkages": [],
        }
        adapter = self._adapter([self._model_response(index) for index in range(1, 6)])

        generate_cases(payload, model_adapter=adapter, test_point_ids=["point-1"])

        scope = json.loads(adapter.adapter.run.call_args_list[0].kwargs["text"])
        self.assertEqual([item["id"] for item in scope["functions"]], ["function-1"])
        self.assertEqual([item["id"] for item in scope["test_points"]], ["point-1"])

    def test_selected_point_gets_explicit_design_method_cases(self):
        result = generate_cases(_generation_payload(), test_point_ids=["point-1"])

        self.assertEqual(
            {item["test_design_method"] for item in result.cases},
            {"equivalence_class", "error_guessing", "boundary_value", "cause_effect_graph", "state_transition"},
        )
        self.assertEqual(
            result.coverage_report["design_methods"],
            {
                "equivalence_class": 1,
                "boundary_value": 1,
                "error_guessing": 1,
                "cause_effect_graph": 1,
                "state_transition": 1,
            },
        )

    def test_model_output_is_constrained_to_selected_points_and_dynamic_budget(self):
        payload = {
            **_generation_payload(),
            "test_points": [
                {"id": "point-positive", "function_id": "function-1", "type": "positive", "description": "有效账号登录"},
                {"id": "point-negative", "function_id": "function-1", "type": "negative", "description": "错误密码拒绝"},
            ],
        }
        responses = []
        for _ in range(5):
            responses.append({
                "cases": [
                    {
                        "source_function_id": "function-1",
                        "source_test_point_id": "point-positive",
                        "type": "positive",
                        "test_design_method": "positive_flow",
                        "scenario_key": f"positive-{index}",
                        "title": f"有效登录场景 {index}",
                        "steps": [f"执行有效登录 {index}"],
                        "expected_result": "登录成功",
                    }
                    for index in range(10)
                ] + [
                    {
                        "source_function_id": "function-1",
                        "source_test_point_id": "point-negative",
                        "type": "negative",
                        "test_design_method": "error_guessing",
                        "scenario_key": f"negative-{index}",
                        "title": f"错误登录场景 {index}",
                        "steps": [f"执行错误登录 {index}"],
                        "expected_result": "提示登录失败",
                    }
                    for index in range(10)
                ] + [{
                    "source_function_id": "function-1",
                    "source_test_point_id": "point-not-selected",
                    "type": "positive",
                    "title": "越界用例",
                    "steps": ["执行越界场景"],
                    "expected_result": "不应进入结果",
                }],
            })

        result = generate_cases(
            payload,
            model_adapter=self._adapter(responses),
            test_point_ids=["point-positive", "point-negative"],
        )

        self.assertTrue(result.cases)
        self.assertTrue({item["source_test_point_id"] for item in result.cases} <= {"point-positive", "point-negative"})
        self.assertLessEqual(sum(item["source_test_point_id"] == "point-positive" for item in result.cases), 5)
        self.assertLessEqual(sum(item["source_test_point_id"] == "point-negative" for item in result.cases), 3)
        self.assertGreater(result.coverage_report["scope_guard"]["model_cases_rejected_out_of_scope"], 0)
        self.assertGreater(result.coverage_report["scope_guard"]["model_cases_rejected_over_limit"], 0)

    def test_model_expanded_design_method_is_normalized_to_legacy_category(self):
        adapter = self._adapter([{
            "cases": [{
                "source_function_id": "function-1",
                "type": "equivalence_class",
                "title": "有效账号等价类",
                "steps": ["输入有效账号"],
                "expected_result": "登录成功",
            }],
        }] * 5)

        result = generate_cases(_generation_payload(), model_adapter=adapter)

        equivalence_case = next(item for item in result.cases if item["test_design_method"] == "equivalence_class")
        self.assertEqual(equivalence_case["type"], "positive")


class T156ReviewTests(TestCase):
    """Verify review round failure persistence and route-aware status."""

    def setUp(self) -> None:
        user = get_user_model().objects.create_user(username="t156-review-owner")
        project = Project.objects.create(name="T156 review project", created_by=user)
        document = RequirementDocument.objects.create(project=project, title="登录", content_text="用户可以登录系统。", created_by=user)
        analysis = analyze_requirement_document(document)
        analysis.coverage_report = {**analysis.coverage_report, "manual_confirmation": {"confirmed": True}}
        analysis.save(update_fields=("coverage_report",))
        self.record = generate_document_cases(document, analysis)

    @staticmethod
    def _review_response() -> dict:
        return {"issues": [], "corrections": [], "approved": True, "summary": "通过", "coverage_report": {}}

    def test_review_failure_keeps_failed_round_and_record_status(self):
        model = ModelConfig.objects.create(
            name="t156-review-model",
            provider=ModelConfig.Provider.CUSTOM,
            model_name="fake",
            model_type=ModelConfig.ModelType.CHAT,
        )
        ModelRoutingPolicy.objects.create(feature_key=ModelRoutingPolicy.FeatureKey.CASE_REVIEW, primary_model=model)
        adapter = Mock()
        adapter.review.side_effect = [self._review_response(), ModelAnalysisError("provider unavailable", code="timeout")]
        with self.assertRaises(CaseReviewError) as context:
            review_generation_record(self.record, model_adapter=adapter)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, CaseGenerationRecord.Status.FAILED)
        self.assertEqual(self.record.review_rounds, 2)
        self.assertEqual(self.record.review_report["round_trace"][-1]["status"], "failed")
        self.assertEqual(self.record.review_report["round_trace"][-1]["error_code"], "timeout")

    def test_model_review_success_is_exactly_five_rounds(self):
        adapter = Mock()
        adapter.review.return_value = self._review_response()
        result = review_cases(self.record, model_adapter=adapter)
        self.assertEqual(adapter.review.call_count, 5)
        self.assertEqual(len(result.round_trace), 5)
        self.assertEqual(result.report["analysis_method"], "model_verified")
