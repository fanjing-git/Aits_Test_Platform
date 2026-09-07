"""Focused tests for the optional structured requirement model adapter."""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.configs.models import ModelConfig
from apps.projects.models import Project
from apps.requirement_analysis.analyzer import analyze_requirement_document
from apps.requirement_analysis.llm_adapter import ModelAnalysisError, OpenAICompatibleRuntime, RequirementModelAdapter
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

    def test_unrelated_model_output_is_rejected(self) -> None:
        runtime = Mock()
        runtime.generate_structured.return_value = {
            "modules": [{"id": "m1", "name": "登录"}],
            "functions": [{"id": "f1", "name": "登录"}],
            "linkages": [],
            "test_points": [{"id": "p1", "description": "验证登录", "evidence_ids": ["known"]}],
        }
        manager = Mock()
        manager.execute_with_fallback.side_effect = lambda _task, operation, **_kwargs: operation(runtime, SimpleNamespace(name="fake"))
        prompts = Mock(); prompts.resolve.return_value = SimpleNamespace(content="JSON")
        with self.assertRaises(ModelAnalysisError):
            RequirementModelAdapter(model_manager=manager, prompt_manager=prompts).analyze(text="背包整理", evidence=[{"id": "known", "text": "背包整理"}])

    def test_deepseek_disables_reasoning_for_structured_output(self) -> None:
        config = ModelConfig(provider=ModelConfig.Provider.DEEPSEEK, model_name="deepseek-v4-flash", api_base_url="https://example.test/v1", parameters={})
        response = Mock()
        response.read.return_value = json.dumps({"choices": [{"message": {"content": '{"ok": true}'}}]}).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch("apps.requirement_analysis.llm_adapter.urlopen", return_value=response) as opener:
            result = OpenAICompatibleRuntime(config).generate_structured(prompt="JSON", text="text", evidence=[])
        self.assertEqual(result, {"ok": True})
        request = opener.call_args.args[0]
        body = json.loads(request.data.decode())
        self.assertEqual(body["thinking"], {"type": "disabled"})

    def test_qwen_uses_compatible_default_base_and_bearer_key(self) -> None:
        config = ModelConfig(provider=ModelConfig.Provider.QWEN, model_name="qwen-max", api_base_url="", parameters={})
        config.api_key_encrypted = "encrypted"
        response = Mock()
        response.read.return_value = json.dumps({"choices": [{"message": {"content": '{"ok": true}'}}]}).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(config, "get_api_key", return_value="qwen-test-key"), patch("apps.requirement_analysis.llm_adapter.urlopen", return_value=response) as opener:
            result = OpenAICompatibleRuntime(config).generate_structured(prompt="JSON", text="text", evidence=[])
        self.assertEqual(result, {"ok": True})
        request = opener.call_args.args[0]
        self.assertIn("dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer qwen-test-key")

    def test_multimodal_payload_includes_image_data_url(self) -> None:
        config = ModelConfig(provider=ModelConfig.Provider.DEEPSEEK, model_name="vision", api_base_url="https://example.test/v1", parameters={})
        response = Mock()
        response.read.return_value = json.dumps({"choices": [{"message": {"content": '{"ok": true}'}}]}).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch("apps.requirement_analysis.llm_adapter.urlopen", return_value=response) as opener:
            OpenAICompatibleRuntime(config).generate_structured(prompt="JSON", text="OCR", evidence=[], image_bytes=b"png", image_mime_type="image/png")
        body = json.loads(opener.call_args.args[0].data.decode())
        content = body["messages"][1]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))


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
