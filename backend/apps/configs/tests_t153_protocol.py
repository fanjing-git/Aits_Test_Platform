"""Mock protocol coverage for native non-OpenAI provider adapters."""

import json
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.test import SimpleTestCase

from apps.configs.catalog import provider_catalog
from apps.configs.models import ModelConfig
from apps.configs.services import ProviderConnectionTester, ProviderError, inference_probe
from apps.requirement_analysis.llm_adapter import OpenAICompatibleRuntime


class JsonResponse:
    """A bounded, file-like fake provider response."""

    def __init__(self, body: object) -> None:
        self.body = json.dumps(body).encode()

    def __enter__(self) -> "JsonResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        return self.body[:size]


class NativeProtocolTests(SimpleTestCase):
    """Verify native request paths, authentication and response normalization."""

    def setUp(self) -> None:
        self.env = patch.dict("os.environ", {"MODEL_CONFIG_FERNET_KEY": Fernet.generate_key().decode()})
        self.env.start()
        self.addCleanup(self.env.stop)

    def config(self, provider: str, *, model_type: str = "chat") -> ModelConfig:
        """Create an unsaved model configuration with a fake provider key."""
        config = ModelConfig(provider=provider, model_type=model_type, model_name="test-model")
        config.set_api_key("fake-provider-key")
        return config

    def test_catalog_declares_only_adapted_capabilities(self) -> None:
        catalog = {item["value"]: item for item in provider_catalog()}
        self.assertEqual({item["value"] for item in catalog["baidu"]["types"]}, {"chat"})
        self.assertEqual({item["value"] for item in catalog["zhipu"]["types"]}, {"chat"})
        self.assertEqual(catalog["anthropic"]["protocol"], "anthropic_messages")
        self.assertEqual(catalog["google"]["protocol"], "google_gemini")

    def test_anthropic_messages_request_and_response_are_normalized(self) -> None:
        response = JsonResponse({"content": [{"type": "text", "text": '{"ok": true}'}]})
        with patch("apps.configs.services.urlopen", return_value=response) as upstream:
            result = OpenAICompatibleRuntime(self.config("anthropic")).generate_structured(
                prompt="Return JSON",
                text="hello",
                evidence=[],
            )
        request = upstream.call_args.args[0]
        body = json.loads(request.data.decode())
        self.assertEqual(result, {"ok": True})
        self.assertTrue(request.full_url.endswith("/messages"))
        self.assertEqual(request.get_header("X-api-key"), "fake-provider-key")
        self.assertEqual(body["system"], "Return JSON")
        self.assertEqual(body["messages"][0]["role"], "user")
        self.assertEqual(body["max_tokens"], 8192)

    def test_google_gemini_request_and_response_are_normalized(self) -> None:
        response = JsonResponse({"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]})
        with patch("apps.configs.services.urlopen", return_value=response) as upstream:
            result = OpenAICompatibleRuntime(self.config("google")).generate_structured(
                prompt="Return JSON",
                text="hello",
                evidence=[],
            )
        request = upstream.call_args.args[0]
        body = json.loads(request.data.decode())
        self.assertEqual(result, {"ok": True})
        self.assertIn(":generateContent", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "fake-provider-key")
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "Return JSON")
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(body["contents"][0]["role"], "user")

    def test_native_vision_content_is_translated(self) -> None:
        cases = (
            ("anthropic", "source", "base64"),
            ("google", "inlineData", "data"),
        )
        for provider, marker, nested_key in cases:
            with self.subTest(provider=provider):
                response = JsonResponse(
                    {"content": [{"type": "text", "text": '{"ok": true}'}]}
                    if provider == "anthropic"
                    else {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]}
                )
                with patch("apps.configs.services.urlopen", return_value=response) as upstream:
                    OpenAICompatibleRuntime(self.config(provider, model_type="vision")).generate_structured(
                        prompt="Return JSON",
                        text="hello",
                        evidence=[],
                        image_bytes=b"png",
                        image_mime_type="image/png",
                    )
                body = json.loads(upstream.call_args.args[0].data.decode())
                serialized = json.dumps(body)
                self.assertIn(marker, serialized)
                self.assertIn(nested_key, serialized)

    def test_baidu_and_zhipu_use_declared_chat_paths(self) -> None:
        for provider, expected_host in (("baidu", "qianfan.baidubce.com"), ("zhipu", "open.bigmodel.cn")):
            with self.subTest(provider=provider):
                response = JsonResponse({"choices": [{"message": {"content": '{"ok": true}'}}]})
                with patch("apps.configs.services.urlopen", return_value=response) as upstream:
                    result = OpenAICompatibleRuntime(self.config(provider)).generate_structured(
                        prompt="Return JSON",
                        text="hello",
                        evidence=[],
                    )
                request = upstream.call_args.args[0]
                body = json.loads(request.data.decode())
                self.assertEqual(result, {"ok": True})
                self.assertIn(expected_host, request.full_url)
                self.assertTrue(request.full_url.endswith("/chat/completions"))
                self.assertEqual(request.get_header("Authorization"), "Bearer fake-provider-key")
                self.assertFalse(body["stream"])
                if provider == "zhipu":
                    self.assertGreater(body["temperature"], 0)

    def test_unadapted_capability_is_blocked_before_provider_request(self) -> None:
        config = self.config("baidu", model_type="vision")
        with patch("apps.configs.services.urlopen") as upstream:
            with self.assertRaisesRegex(ProviderError, "未声明支持"):
                inference_probe(config)
        upstream.assert_not_called()
        result = ProviderConnectionTester().test(config, mode="inference")
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "capability_not_supported")
