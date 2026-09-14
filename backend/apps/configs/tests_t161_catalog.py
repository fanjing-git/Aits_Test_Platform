"""T161 coverage for catalog provenance, account states and manual providers."""

import json
from datetime import date
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.configs.catalog import (
    is_reference_snapshot_stale,
    provider_catalog,
)
from apps.configs.models import ModelConfig
from apps.configs.services import ProviderConnectionTester, discover_models


class JsonResponse:
    """Small provider response double with the same bounded interface as urlopen."""

    def __init__(self, body: object) -> None:
        self.body = json.dumps(body).encode()

    def __enter__(self) -> "JsonResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        return self.body[:size]


class CatalogContractTests(SimpleTestCase):
    """Keep reference, live and manual catalog states distinguishable."""

    def setUp(self) -> None:
        self.environment = patch.dict("os.environ", {"MODEL_CONFIG_FERNET_KEY": Fernet.generate_key().decode()})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def config(self, provider: str, model_name: str = "test-model") -> ModelConfig:
        """Build an unsaved model config for a non-billable catalog test."""
        config = ModelConfig(provider=provider, model_name=model_name, model_type="chat")
        config.set_api_key("fake-provider-key")
        return config

    def test_reference_snapshot_exposes_provenance_and_stale_state(self) -> None:
        catalog = {item["value"]: item for item in provider_catalog()}
        deepseek = catalog["deepseek"]
        self.assertEqual(deepseek["source_kind"], "reference_snapshot")
        self.assertEqual(deepseek["source_version"], "reference-2026-09-07")
        self.assertEqual(deepseek["directory_state"], "reference_only")
        self.assertTrue(is_reference_snapshot_stale("2026-09-01", today=date(2026, 9, 10)))
        self.assertFalse(is_reference_snapshot_stale("2026-09-07", today=date(2026, 9, 10)))

    def test_manual_providers_never_receive_fake_reference_models(self) -> None:
        catalog = {item["value"]: item for item in provider_catalog()}
        for provider in ("azure", "custom", "local"):
            with self.subTest(provider=provider):
                self.assertEqual(catalog[provider]["source_kind"], "manual_only")
                self.assertEqual(catalog[provider]["directory_state"], "manual_only")
                self.assertEqual(catalog[provider]["models"], [])
                self.assertTrue(catalog[provider]["manual_model_id_allowed"])

    def test_live_directory_marks_account_access_but_not_model_call(self) -> None:
        with patch("apps.configs.services.urlopen", return_value=JsonResponse({"data": [{"id": "test-model"}]})):
            page = discover_models(self.config("deepseek"))
        self.assertEqual(page["source_kind"], "provider_directory")
        self.assertEqual(page["directory_state"], "available")
        self.assertEqual(page["account_access_state"], "catalog_accessible")
        self.assertEqual(page["model_call_state"], "not_checked")
        self.assertFalse(page["is_stale"])

        with patch("apps.configs.services.urlopen", return_value=JsonResponse({"data": [{"id": "test-model"}]})):
            result = ProviderConnectionTester().test(self.config("deepseek"))
        self.assertTrue(result.ok)
        self.assertEqual(result.model_state, "listed")
        self.assertEqual(result.model_call_state, "not_checked")

    def test_manual_discovery_returns_explicit_hand_entry_without_network(self) -> None:
        with patch("apps.configs.services.urlopen") as upstream:
            page = discover_models(self.config("custom"))
        upstream.assert_not_called()
        self.assertEqual(page["source_kind"], "manual_only")
        self.assertEqual(page["directory_state"], "manual_only")
        self.assertEqual(page["models"], [])
        result = ProviderConnectionTester().test(self.config("custom"))
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "manual_model_required")
        self.assertEqual(result.model_state, "manual_required")


class CatalogApiTests(APITestCase):
    """Verify the selector metadata is available only through the admin API."""

    def setUp(self) -> None:
        self.admin = get_user_model().objects.create_user(username="t161-admin")
        self.admin.profile.role = "admin"
        self.admin.profile.save()

    def test_catalog_includes_state_metadata_and_no_credentials(self) -> None:
        self.client.force_authenticate(self.admin)
        response = self.client.get("/api/configs/models/catalog/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("api_key", json.dumps(response.data))
        providers = {item["value"]: item for item in response.data["providers"]}
        self.assertIn("directory_state", providers["openai"])
        self.assertEqual(providers["custom"]["source_kind"], "manual_only")

    def test_catalog_requires_authentication(self) -> None:
        response = self.client.get("/api/configs/models/catalog/")
        self.assertEqual(response.status_code, 401)
