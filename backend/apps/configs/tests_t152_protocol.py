"""Regression coverage for the shared OpenAI-compatible protocol contract."""

import json
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.test import SimpleTestCase

from apps.configs.models import ModelConfig
from apps.configs.services import (
    MAX_STRUCTURED_TIMEOUT_SECONDS,
    ProviderError,
    openai_compatible_chat,
    parse_openai_json_response,
    structured_timeout,
)
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


class OpenAICompatibleProtocolTests(SimpleTestCase):
    """Ensure probes and structured business calls share provider parameters."""

    def setUp(self) -> None:
        self.env = patch.dict("os.environ", {"MODEL_CONFIG_FERNET_KEY": Fernet.generate_key().decode()})
        self.env.start()
        self.addCleanup(self.env.stop)

    def config(self, provider: str, *, base_url: str = "", parameters: dict | None = None) -> ModelConfig:
        """Create an unsaved compatible model configuration with a fake key."""
        config = ModelConfig(
            provider=provider,
            model_type=ModelConfig.ModelType.CHAT,
            model_name="test-model",
            api_base_url=base_url,
            parameters=parameters or {},
        )
        config.set_api_key("fake-provider-key")
        return config

    def test_protocol_fields_are_consistent_for_supported_providers(self) -> None:
        cases = {
            "qwen": {"token": "max_tokens", "extra": {"enable_thinking": False}},
            "deepseek": {"token": "max_tokens", "extra": {"thinking": {"type": "disabled"}}},
            "openai": {"token": "max_completion_tokens", "extra": {}},
            "azure": {"token": "max_completion_tokens", "extra": {}},
        }
        for provider, expected in cases.items():
            with self.subTest(provider=provider):
                base_url = "https://resource.openai.azure.com" if provider == "azure" else ""
                config = self.config(provider, base_url=base_url)
                response = JsonResponse({"choices": [{"message": {"content": '{"ok": true}'}}]})
                with patch("apps.configs.services.urlopen", return_value=response) as upstream:
                    probe_result = openai_compatible_chat(
                        config,
                        messages=({"role": "user", "content": "probe"},),
                        max_tokens=16,
                    )
                    runtime_result = OpenAICompatibleRuntime(config).generate_structured(
                        prompt="JSON",
                        text="text",
                        evidence=[],
                    )
                self.assertEqual(probe_result, {"choices": [{"message": {"content": '{"ok": true}'}}]})
                self.assertEqual(runtime_result, {"ok": True})
                self.assertEqual(upstream.call_count, 2)
                for call in upstream.call_args_list:
                    request = call.args[0]
                    body = json.loads(request.data.decode())
                    self.assertEqual(body[expected["token"]], 16 if call is upstream.call_args_list[0] else 8192)
                    self.assertNotIn("max_tokens", body) if expected["token"] == "max_completion_tokens" else None
                    self.assertEqual(body["response_format"], {"type": "json_object"})
                    self.assertFalse(body["stream"])
                    for key, value in expected["extra"].items():
                        self.assertEqual(body[key], value)

    def test_structured_timeout_is_bounded(self) -> None:
        config = self.config("openai", parameters={"structured_timeout_seconds": 999})
        response = JsonResponse({"choices": [{"message": {"content": '{"ok": true}'}}]})
        with patch("apps.configs.services.urlopen", return_value=response) as upstream:
            openai_compatible_chat(
                config,
                messages=({"role": "user", "content": "probe"},),
                max_tokens=16,
            )
        self.assertEqual(structured_timeout(config), MAX_STRUCTURED_TIMEOUT_SECONDS)
        self.assertEqual(upstream.call_args.kwargs["timeout"], MAX_STRUCTURED_TIMEOUT_SECONDS)

    def test_multipart_and_fenced_json_are_parsed_without_leaking_content(self) -> None:
        response = {
            "choices": [{"message": {"content": [{"type": "text", "text": "```json\n"}, {"text": '{"ok": true}\n```'}]}}]
        }
        self.assertEqual(parse_openai_json_response(response), {"ok": True})
        with self.assertRaisesRegex(ProviderError, "有效 JSON"):
            parse_openai_json_response({"choices": [{"message": {"content": "not-json"}}]})
