"""Focused tests for the five-round case generation pipeline."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from unittest.mock import Mock, patch

from apps.configs.models import ModelConfig
from apps.case_generation.generator import CaseGenerationError, generate_cases, generate_document_cases
from apps.case_generation.llm_adapter import CaseGenerationModelAdapter
from apps.case_generation.models import CaseGenerationRecord
from apps.projects.models import Project
from apps.requirement_analysis.analyzer import analyze_requirement_document
from apps.requirement_analysis.llm_adapter import ModelAnalysisError
from apps.requirement_analysis.linkages import identify_document_linkages
from apps.requirement_analysis.models import RequirementDocument


class CaseGenerationTests(TestCase):
    """Verify round trace, coverage and persisted generation output."""

    def test_five_rounds_cover_function_and_linkage_scenarios(self) -> None:
        payload = {"functions": [{"id": "account-login", "module_id": "account", "name": "用户登录"}, {"id": "order-create", "module_id": "order", "name": "创建订单"}], "linkages": [{"id": "link-1", "from": "account-login", "to": "order-create"}]}
        result = generate_cases(payload)
        self.assertEqual([item["round"] for item in result.round_trace], [1, 2, 3, 4, 5])
        self.assertEqual(result.coverage_report["coverage_rate"], 1.0)
        self.assertEqual({item["type"] for item in result.cases}, {"positive", "negative", "boundary", "linkage"})

    def test_missing_functions_fail_safely(self) -> None:
        with self.assertRaises(CaseGenerationError): generate_cases({"functions": []})

    def test_model_generation_runs_five_incremental_rounds_and_preserves_scenarios(self) -> None:
        payload = {
            "modules": [{"id": "module-account", "name": "账户"}],
            "functions": [{"id": "login", "module_id": "module-account", "name": "登录"}],
            "test_points": [{"id": "tp-login", "function_id": "login", "description": "登录校验"}],
            "linkages": [],
        }
        adapter = CaseGenerationModelAdapter.__new__(CaseGenerationModelAdapter)
        adapter.adapter = Mock()
        responses = [
            {"cases": [{"source_function_id": "login", "type": "positive", "title": f"登录场景{index}", "steps": [f"执行步骤{index}"], "expected_result": "登录成功"}]}
            for index in range(1, 6)
        ]
        adapter.adapter.run.side_effect = responses
        result = generate_cases(payload, model_adapter=adapter, document_text="用户可以登录系统。")
        self.assertEqual(adapter.adapter.run.call_count, 5)
        self.assertEqual([item["stage"] for item in result.round_trace], ["model_incremental"] * 5)
        self.assertEqual(result.coverage_report["model_rounds"], [1, 2, 3, 4, 5])
        self.assertEqual(result.coverage_report["case_count"], 5)

    def test_document_generation_persists_completed_record(self) -> None:
        user = get_user_model().objects.create_user(username="case-generator-owner")
        project = Project.objects.create(name="Case generator project", created_by=user)
        document = RequirementDocument.objects.create(project=project, title="Order", content_text="# Account\n用户登录。\n# Order\n系统创建订单。", created_by=user)
        analysis = analyze_requirement_document(document)
        identify_document_linkages(analysis)
        record = generate_document_cases(document, analysis)
        self.assertEqual(record.status, CaseGenerationRecord.Status.COMPLETED)
        self.assertEqual(record.rounds, 5)
        self.assertGreater(record.total_cases, 0)
        self.assertEqual(record.coverage_report["coverage_rate"], 1.0)

    def test_active_model_cases_are_accepted_and_traced(self) -> None:
        user = get_user_model().objects.create_user(username="case-model-owner")
        project = Project.objects.create(name="Case model project", created_by=user)
        document = RequirementDocument.objects.create(project=project, title="Order", content_text="用户登录。", created_by=user)
        analysis = analyze_requirement_document(document)
        ModelConfig.objects.create(name="case-fake-chat", provider=ModelConfig.Provider.CUSTOM, model_name="fake", model_type=ModelConfig.ModelType.CHAT)
        fake = Mock()
        fake.generate.return_value = {"cases": [{"id": "draft-1", "title": "用户登录 - 正常流程", "type": "positive", "source_function_id": analysis.functions[0]["id"], "steps": ["执行登录"], "expected_result": "登录成功"}], "coverage_report": {}, "round_trace": []}
        with patch("apps.case_generation.generator.CaseGenerationModelAdapter", return_value=fake):
            record = generate_document_cases(document, analysis)
        self.assertEqual(record.coverage_report["analysis_method"], "model_verified")
        self.assertTrue(record.cases)

    def test_configured_model_failure_does_not_persist_deterministic_cases(self) -> None:
        user = get_user_model().objects.create_user(username="case-model-failure-owner")
        project = Project.objects.create(name="Case model failure project", created_by=user)
        document = RequirementDocument.objects.create(project=project, title="Order", content_text="登录", created_by=user)
        analysis = analyze_requirement_document(document)
        ModelConfig.objects.create(name="case-failing-chat", provider=ModelConfig.Provider.CUSTOM, model_name="fake", model_type=ModelConfig.ModelType.CHAT)
        failing = Mock()
        failing.generate.side_effect = ModelAnalysisError("provider unavailable")
        with patch("apps.case_generation.generator.CaseGenerationModelAdapter", return_value=failing):
            with self.assertRaises(CaseGenerationError):
                generate_document_cases(document, analysis)
        record = CaseGenerationRecord.objects.get(document=document)
        self.assertEqual(record.status, CaseGenerationRecord.Status.FAILED)
        self.assertEqual(record.total_cases, 0)
