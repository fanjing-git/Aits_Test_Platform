"""Connection adapter regression tests added during the V5.3 audit."""

from unittest.mock import patch

from cryptography.fernet import Fernet
from django.test import SimpleTestCase, override_settings

from apps.configs.models import ModelConfig
from apps.configs.services import ProviderConnectionTester
from core.utils.crypto import MODEL_CONFIG_FERNET_KEY_ENV


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ProviderConnectionTesterAuditTests(SimpleTestCase):
    def setUp(self):
        self.key = Fernet.generate_key().decode("ascii")
        self.environment = patch.dict("os.environ", {MODEL_CONFIG_FERNET_KEY_ENV: self.key})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.config = ModelConfig(
            name="audit-model",
            provider="deepseek",
            model_name="deepseek-v4-flash",
            api_base_url="https://api.deepseek.com",
        )
        self.config.set_api_key("test-key")

    @override_settings(**{MODEL_CONFIG_FERNET_KEY_ENV: ""})
    def test_missing_endpoint_is_actionable(self):
        self.config.api_base_url = ""
        self.config.provider = "custom"
        result = ProviderConnectionTester().test(self.config)
        self.assertFalse(result.ok)
        self.assertIn("API", result.message)

    def test_successful_models_probe(self):
        with patch(
            "apps.configs.services.urlopen", return_value=_Response()
        ) as mocked:
            result = ProviderConnectionTester().test(self.config)
        self.assertTrue(result.ok)
        self.assertIn("deepseek", result.message)
        self.assertEqual(mocked.call_args.kwargs["timeout"], 8)

    def test_http_failure_is_reported_without_secret(self):
        from urllib.error import HTTPError

        error = HTTPError("https://api.deepseek.com/models", 401, "Unauthorized", {}, None)
        with patch(
            "apps.configs.services.urlopen", side_effect=error
        ):
            result = ProviderConnectionTester().test(self.config)
        self.assertFalse(result.ok)
        self.assertIn("401", result.message)
        self.assertNotIn("test-key", result.message)
