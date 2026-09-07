"""Regression coverage for provider protocols, discovery and configuration UX APIs."""

import json
from unittest.mock import patch
from urllib.error import HTTPError

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.configs.catalog import normalize_model, provider_catalog
from apps.configs.models import ModelConfig
from apps.configs.services import ProviderConnectionTester, ProviderError, canonical_base, discover_models


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


class ProviderDiscoveryTests(SimpleTestCase):
    """Verify protocols without network access or billable requests."""

    def setUp(self) -> None:
        self.env = patch.dict("os.environ", {"MODEL_CONFIG_FERNET_KEY": Fernet.generate_key().decode()})
        self.env.start()
        self.addCleanup(self.env.stop)

    def config(self, provider: str = "qwen", kind: str = "chat") -> ModelConfig:
        """Create an unsaved config with a fake credential."""
        result = ModelConfig(provider=provider, model_type=kind, model_name="test-model")
        result.set_api_key("fake-provider-key")
        return result

    def test_qwen_native_catalog_and_all_capabilities_paginate(self) -> None:
        config = self.config()
        config.api_base_url = "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        with patch("apps.configs.services.urlopen", return_value=JsonResponse({"output": {
            "total": 2, "page_size": 1, "models": [{"model": "future-model", "capabilities": ["TG", "VU", "TTS"]}]
        }})) as upstream:
            first = discover_models(config)
        request = upstream.call_args.args[0]
        self.assertIn("/api/v1/models?page_no=1", request.full_url)
        self.assertNotIn("compatible-mode", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer fake-provider-key")
        self.assertEqual(first["models"][0]["types"], ["chat", "tts", "vision"])
        self.assertEqual(first["next_cursor"], "2")
        with patch("apps.configs.services.urlopen", return_value=JsonResponse({"output": {
            "total": 2, "page_size": 1, "models": [{"model": "test-model"}]
        }})) as upstream:
            last = discover_models(config, "2")
        self.assertIn("page_no=2", upstream.call_args.args[0].full_url)
        self.assertTrue(last["complete"])
        self.assertEqual(last["models"][0]["types"], ["other"])

    def test_provider_authentication_and_pagination(self) -> None:
        cases = [
            ("anthropic", {"data": [{"id": "claude-test"}], "has_more": True, "last_id": "claude-test"}, "X-api-key", "fake-provider-key", "claude-test"),
            ("google", {"models": [{"name": "models/gemini-test", "supportedGenerationMethods": ["embedContent"]}], "nextPageToken": "page-token"}, "X-goog-api-key", "fake-provider-key", "page-token"),
            ("azure", {"data": [{"id": "deployed-model"}]}, "Api-key", "fake-provider-key", ""),
            ("baidu", {"data": [{"id": "ernie-test"}]}, "Authorization", "Bearer fake-provider-key", ""),
        ]
        for provider, body, header, key, next_cursor in cases:
            with self.subTest(provider=provider):
                config = self.config(provider)
                if provider == "azure":
                    config.api_base_url = "https://resource.openai.azure.com"
                with patch("apps.configs.services.urlopen", return_value=JsonResponse(body)) as upstream:
                    result = discover_models(config)
                request = upstream.call_args.args[0]
                self.assertEqual(request.get_header(header), key)
                if provider != "baidu":
                    self.assertIsNone(request.get_header("Authorization"))
                self.assertEqual(result["next_cursor"], next_cursor)
                if provider == "anthropic":
                    self.assertEqual(request.get_header("Anthropic-version"), "2023-06-01")
                if provider == "azure":
                    self.assertIn("/openai/v1/models", request.full_url)

    def test_coding_plan_does_not_switch_hosts_or_use_native_catalog(self) -> None:
        config = self.config()
        config.api_base_url = "https://coding.dashscope.aliyuncs.com/v1"
        with patch("apps.configs.services.urlopen", return_value=JsonResponse({"data": []})) as upstream:
            self.assertEqual(discover_models(config)["models"], [])
        self.assertEqual(upstream.call_args.args[0].full_url, config.api_base_url + "/models")

    def test_invalid_and_empty_catalogs_do_not_claim_model_success(self) -> None:
        for body in ({}, {"data": []}, {"data": [42]}, {"data": [{"id": "another-model"}]}, {"success": False}):
            with self.subTest(body=body), patch("apps.configs.services.urlopen", return_value=JsonResponse(body)):
                self.assertFalse(ProviderConnectionTester().test(self.config("deepseek")).ok)

    def test_failures_are_actionable_and_never_echo_keys_or_upstream_bodies(self) -> None:
        for code in (301, 400, 401, 403, 404, 429, 500):
            with self.subTest(code=code), patch("apps.configs.services.urlopen", side_effect=HTTPError("https://example.test", code, "fake-provider-key", {}, None)):
                result = ProviderConnectionTester().test(self.config())
                self.assertFalse(result.ok)
                self.assertIn(str(code), result.message)
                self.assertNotIn("fake-provider-key", result.message)

    def test_windows_network_policy_error_is_distinguished(self) -> None:
        class SocketPolicyError(OSError):
            winerror = 10013

        with patch("apps.configs.services.urlopen", side_effect=SocketPolicyError("blocked")):
            result = ProviderConnectionTester().test(self.config())
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "local_network_blocked")
        self.assertIn("10013", result.message)

    def test_catalog_success_is_not_inference_success(self) -> None:
        with patch("apps.configs.services.urlopen", return_value=JsonResponse({"data": [{"id": "test-model"}]})):
            result = ProviderConnectionTester().test(self.config("deepseek"))
        self.assertTrue(result.ok)
        self.assertFalse(result.inference_verified)

    def test_explicit_qwen_inference_works_when_models_endpoint_is_unavailable(self) -> None:
        with patch("apps.configs.services.urlopen", return_value=JsonResponse({"choices": [{"message": {"content": "OK"}}]})) as upstream:
            result = ProviderConnectionTester().test(self.config(), mode="inference")
        self.assertTrue(result.inference_verified)
        request = upstream.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/chat/completions"))
        self.assertFalse(json.loads(request.data)["enable_thinking"])
        self.assertEqual(upstream.call_count, 1)

    def test_native_inference_probes(self) -> None:
        cases = [
            ("google", "embedding", {"embedding": {"values": [0.1]}}, ":embedContent"),
            ("google", "chat", {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}, ":generateContent"),
            ("anthropic", "chat", {"type": "message", "content": [{"type": "text", "text": "OK"}]}, "/messages"),
            ("custom", "embedding", {"data": [{"embedding": [0.1]}]}, "/embeddings"),
        ]
        for provider, kind, body, suffix in cases:
            with self.subTest(provider=provider, kind=kind):
                config = self.config(provider, kind)
                if provider == "custom":
                    config.api_base_url = "http://127.0.0.1:8099/v1"
                with patch("apps.configs.services.urlopen", return_value=JsonResponse(body)) as upstream:
                    result = ProviderConnectionTester().test(config, "inference")
                self.assertTrue(result.ok, result.message)
                self.assertTrue(upstream.call_args.args[0].full_url.endswith(suffix))

    def test_unsafe_urls_and_unknown_capabilities(self) -> None:
        for address in ("file:///etc/passwd", "https://user:secret@example.test", "https://example.test?key=secret"):
            with self.assertRaises(ProviderError):
                canonical_base("custom", address)
        item = normalize_model({"id": "brand-new-model", "capabilities": ["new-kind"]}, "custom")
        self.assertEqual(item["types"], ["other"])
        self.assertEqual(item["id"], "brand-new-model")
        qwen = next(item for item in provider_catalog() if item["value"] == "qwen")
        self.assertFalse(qwen["complete"])
        self.assertGreater(len(qwen["models"]), 20)


class DiscoveryApiTests(APITestCase):
    """Protect draft credentials, account access and new model types."""

    def setUp(self) -> None:
        self.env = patch.dict("os.environ", {"MODEL_CONFIG_FERNET_KEY": Fernet.generate_key().decode()})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.admin = get_user_model().objects.create_user(username="discovery-admin")
        self.admin.profile.role = "admin"
        self.admin.profile.save()
        self.client.force_authenticate(self.admin)
        self.url = "/api/configs/models/discover/"
        self.config = ModelConfig(provider="qwen", name="stored", model_name="test-model")
        self.config.set_api_key("stored-secret")
        self.config.save()

    def test_draft_and_saved_discovery_never_expose_or_persist_keys(self) -> None:
        for extra in ({"api_key": "draft-secret"}, {"config_id": self.config.pk}):
            with patch("apps.configs.services.urlopen", return_value=JsonResponse({"output": {"models": [], "total": 0}})):
                response = self.client.post(self.url, {"provider": "qwen", **extra}, format="json")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("secret", json.dumps(response.data))
            self.assertEqual(ModelConfig.objects.count(), 1)

    def test_saved_key_cannot_be_redirected_by_draft_address_or_provider(self) -> None:
        for override in ({"api_base_url": "https://attacker.example/v1"}, {"provider": "google"}):
            with patch("apps.configs.services.urlopen") as upstream:
                response = self.client.post(self.url, {"provider": "qwen", "config_id": self.config.pk, **override}, format="json")
            self.assertEqual(response.status_code, 400)
            upstream.assert_not_called()
        response = self.client.patch(f"/api/configs/models/{self.config.pk}/", {"provider": "google"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_validation_and_role_boundaries(self) -> None:
        self.assertEqual(self.client.post(self.url, {"provider": "invalid"}).status_code, 400)
        viewer = get_user_model().objects.create_user(username="discovery-viewer")
        self.client.force_authenticate(viewer)
        self.assertEqual(self.client.post(self.url, {"provider": "qwen"}).status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(self.url, {"provider": "qwen"}).status_code, 401)

    def test_new_types_save_and_test_modes_are_explicit(self) -> None:
        for kind in ("tts", "rerank", "image_generation", "multimodal", "video", "asr"):
            response = self.client.post("/api/configs/models/", {"name": kind, "provider": "qwen", "model_type": kind, "model_name": "custom-deployment"}, format="json")
            self.assertEqual(response.status_code, 201)
        url = f"/api/configs/models/{self.config.pk}/test-connection/"
        self.assertEqual(self.client.post(url, {"mode": "bad"}).status_code, 400)
        with patch("apps.configs.services.urlopen", return_value=JsonResponse({"choices": [{"message": {"content": "OK"}}]})):
            response = self.client.post(url, {"mode": "inference"})
        self.assertTrue(response.data["inference_verified"])
