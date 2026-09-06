"""Focused tests for the optional structured requirement model adapter."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.configs.models import ModelConfig
from apps.projects.models import Project
from apps.requirement_analysis.analyzer import analyze_requirement_document
from apps.requirement_analysis.llm_adapter import ModelAnalysisError, RequirementModelAdapter
from apps.requirement_analysis.models import RequirementDocument


class RequirementModelAdapterTests(SimpleTestCase):
    """Verify prompt routing, evidence validation and safe model fallback."""

    def test_valid_structured_output_is_accepted(self) -> None:
        runtime = Mock()
        runtime.generate_structured.return_value = {
            "modules": [{"id": "module-1", "name": "背包", "evidence_ids": ["ocr-1"]}],
            "functions": [{"id": "function-1", "name": "切换材料标签", "evidence_ids": ["ocr-1"]}],
            "linkages": [],
            "test_points": [{"id": "point-1", "description": "确认标签可切换", "evidence_ids": ["ocr-1"]}],
            "coverage_report": {"coverage_rate": 1.0},
        }
        manager = Mock()
        manager.execute_with_fallback.side_effect = lambda _task, operation, **_kwargs: operation(runtime, SimpleNamespace(name="fake"))
        prompts = Mock()
        prompts.resolve.return_value = SimpleNamespace(content="只输出 JSON")
        result = RequirementModelAdapter(model_manager=manager, prompt_manager=prompts).analyze(text="背包", evidence=[{"id": "ocr-1", "text": "背包"}])
        self.assertEqual(result["functions"][0]["name"], "切换材料标签")
        prompts.resolve.assert_called_once()

    def test_untrusted_evidence_reference_is_rejected(self) -> None:
        runtime = Mock()
        runtime.generate_structured.return_value = {"modules": [], "functions": [{"id": "f1", "evidence_ids": ["unknown"]}], "linkages": [], "test_points": []}
        manager = Mock()
        manager.execute_with_fallback.side_effect = lambda _task, operation, **_kwargs: operation(runtime, SimpleNamespace(name="fake"))
        prompts = Mock(); prompts.resolve.return_value = SimpleNamespace(content="JSON")
        with self.assertRaises(ModelAnalysisError):
            RequirementModelAdapter(model_manager=manager, prompt_manager=prompts).analyze(text="内容", evidence=[{"id": "known", "text": "内容"}])


class RequirementModelIntegrationTests(TestCase):
    """Verify an active model uses the adapter while preserving structured output."""

    def test_active_model_result_is_persisted_as_verified(self) -> None:
        user = get_user_model().objects.create_user(username="llm-analysis-owner")
        project = Project.objects.create(name="LLM project", created_by=user)
        document = RequirementDocument.objects.create(project=project, title="登录", content_text="用户登录系统。", created_by=user)
        ModelConfig.objects.create(name="fake-chat", provider=ModelConfig.Provider.CUSTOM, model_name="fake", model_type=ModelConfig.ModelType.CHAT)
        payload = {"modules": [{"id": "m1", "name": "登录"}], "functions": [{"id": "f1", "name": "登录", "evidence_ids": []}], "linkages": [], "test_points": [{"id": "p1", "description": "正常登录", "evidence_ids": []}], "coverage_report": {"coverage_rate": 1.0}}
        fake = Mock(); fake.analyze.return_value = payload
        with patch("apps.requirement_analysis.analyzer.RequirementModelAdapter", return_value=fake):
            result = analyze_requirement_document(document)
        self.assertEqual(result.coverage_report["analysis_method"], "model_verified")
