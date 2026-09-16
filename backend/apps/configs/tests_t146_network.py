"""Focused tests for safe model connection targets and failure taxonomy."""

import socket
import ssl
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.configs.models import ModelConfig
from apps.configs.services import (
    ProviderConnectionTester,
    ProviderError,
    request_json,
    validate_outbound_endpoint,
)


class ModelConnectionNetworkTests(SimpleTestCase):
    """Verify target validation and sanitized network failure stages."""

    def setUp(self) -> None:
        self.environment = patch.dict("os.environ", {"MODEL_CONFIG_FERNET_KEY": Fernet.generate_key().decode()})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.config = ModelConfig(
            provider="deepseek",
            model_name="deepseek-chat",
            model_type="chat",
            api_base_url="https://api.deepseek.com",
        )
        self.config.set_api_key("test-key")

    @staticmethod
    def public_dns(*args: object, **kwargs: object) -> list[tuple[object, object, object, object, tuple[str, int]]]:
        """Return a safe public address without performing DNS in unit tests."""
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("1.1.1.1", 443))]

    def test_allowed_provider_host_requires_safe_resolved_address(self) -> None:
        with patch("apps.configs.services.socket.getaddrinfo", side_effect=self.public_dns):
            validate_outbound_endpoint("deepseek", "https://api.deepseek.com/v1/chat/completions")

    def test_unknown_provider_host_is_rejected_before_dns(self) -> None:
        with patch("apps.configs.services.socket.getaddrinfo") as resolver:
            with self.assertRaisesRegex(ProviderError, "不在允许的域名范围") as raised:
                validate_outbound_endpoint("deepseek", "https://attacker.example/v1")
        self.assertEqual(raised.exception.code, "unsafe_target")
        resolver.assert_not_called()

    def test_private_resolved_address_is_rejected(self) -> None:
        with patch("apps.configs.services.socket.getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.8", 443)),
        ]):
            with self.assertRaisesRegex(ProviderError, "受禁止") as raised:
                validate_outbound_endpoint("deepseek", "https://api.deepseek.com/v1")
        self.assertEqual(raised.exception.code, "unsafe_target")

    def test_local_provider_may_use_localhost_only(self) -> None:
        validate_outbound_endpoint("local", "http://127.0.0.1:11434/v1")
        with self.assertRaisesRegex(ProviderError, "本地模型只能"):
            validate_outbound_endpoint("local", "https://api.deepseek.com/v1")

    def test_network_failure_stages_are_stable_and_sanitized(self) -> None:
        failures = (
            (URLError(socket.gaierror("secret-host")), "dns_failed"),
            (URLError(ssl.SSLError("private-cert")), "tls_failed"),
            (OSError(10013, "blocked"), "local_network_blocked"),
            (URLError(TimeoutError("provider timed out")), "provider_timeout"),
            (URLError("proxy down"), "proxy_unavailable"),
        )
        for failure, code in failures:
            with self.subTest(code=code), patch("apps.configs.services.urlopen", side_effect=failure):
                result = ProviderConnectionTester().test(self.config, mode="inference")
            self.assertFalse(result.ok)
            self.assertEqual(result.code, code)
            self.assertNotIn("secret-host", result.message)
            self.assertNotIn("private-cert", result.message)

    def test_provider_http_failures_use_actionable_categories(self) -> None:
        for status_code, expected_code in ((401, "auth_failed"), (403, "auth_failed"), (402, "quota_exhausted"), (429, "quota_exhausted"), (500, "provider_http_error"), (407, "proxy_unavailable")):
            error = HTTPError("https://api.deepseek.com/v1", status_code, "secret-key", {}, None)
            with self.subTest(status_code=status_code), patch("apps.configs.services.urlopen", side_effect=error):
                with self.assertRaises(ProviderError) as raised:
                    request_json(self.config, "https://api.deepseek.com/v1/chat/completions", {"ping": True})
            self.assertEqual(raised.exception.code, expected_code)
            self.assertNotIn("secret-key", str(raised.exception))

    def test_urlopen_validates_before_building_network_opener(self) -> None:
        with patch("apps.configs.services.build_opener") as opener:
            with self.assertRaisesRegex(ProviderError, "不在允许的域名范围"):
                from apps.configs.services import urlopen

                urlopen(Request("https://attacker.example/v1"), provider="deepseek")
        opener.assert_not_called()


class ConnectionApiNetworkTests(APITestCase):
    """Verify the REST endpoint exposes safe target failures without dialing them."""

    def setUp(self) -> None:
        self.environment = patch.dict("os.environ", {"MODEL_CONFIG_FERNET_KEY": Fernet.generate_key().decode()})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        admin = get_user_model().objects.create_user(username="network-admin")
        admin.profile.role = "admin"
        admin.profile.save()
        self.client.force_authenticate(admin)
        self.config = ModelConfig(
            name="unsafe-target-test",
            provider="deepseek",
            model_name="deepseek-chat",
            model_type="chat",
            api_base_url="https://attacker.example/v1",
        )
        self.config.set_api_key("test-key")
        self.config.save()

    def test_unsafe_target_is_returned_as_actionable_api_error(self) -> None:
        url = f"/api/configs/models/{self.config.pk}/test-connection/"
        with patch("apps.configs.services.socket.getaddrinfo") as resolver:
            response = self.client.post(url, {"mode": "inference"}, format="json")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "unsafe_target")
        resolver.assert_not_called()
