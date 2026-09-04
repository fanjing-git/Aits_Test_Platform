"""REST API tests for task T010."""

import os
from decimal import Decimal
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.configs.models import ModelConfig, ModelUsageRecord
from apps.configs.services import ConnectionTestResult
from apps.configs.views import ModelConfigViewSet
from apps.users.models import UserProfile
from core.utils.crypto import MODEL_CONFIG_FERNET_KEY_ENV


class FakeSuccessfulConnectionTester:
    def test(self, config: ModelConfig) -> ConnectionTestResult:
        return ConnectionTestResult(True, f"Connected to {config.name}.", 12)


class ModelConfigApiTests(APITestCase):
    def setUp(self) -> None:
        self.fernet_key = Fernet.generate_key().decode("ascii")
        self.environment = patch.dict(
            os.environ,
            {MODEL_CONFIG_FERNET_KEY_ENV: self.fernet_key},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

        self.admin = get_user_model().objects.create_user(username="admin-api")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save(update_fields=("role",))
        self.viewer = get_user_model().objects.create_user(username="viewer-api")
        self.client.force_authenticate(self.admin)
        self.list_url = reverse("configs:model-config-list")

    def payload(self, name: str = "primary-model") -> dict[str, object]:
        return {
            "name": name,
            "provider": ModelConfig.Provider.OPENAI,
            "model_name": "example-model",
            "model_type": ModelConfig.ModelType.CHAT,
            "api_key": "fake-key-for-tests-only",
            "api_base_url": "https://models.example.test/v1",
            "parameters": {"temperature": 0.2},
            "is_default": True,
            "is_active": True,
            "priority": 10,
        }

    def test_admin_can_crud_config_without_secret_disclosure(self) -> None:
        create_response = self.client.post(self.list_url, self.payload(), format="json")
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("api_key", create_response.data)
        self.assertNotIn("api_key_encrypted", create_response.data)
        self.assertTrue(create_response.data["has_api_key"])

        config = ModelConfig.objects.get(pk=create_response.data["id"])
        self.assertNotIn("fake-key-for-tests-only", config.api_key_encrypted)
        self.assertEqual(config.get_api_key(), "fake-key-for-tests-only")
        detail_url = reverse("configs:model-config-detail", args=(config.pk,))

        update_response = self.client.patch(
            detail_url,
            {"priority": 3, "api_key": "rotated-fake-key"},
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        config.refresh_from_db()
        self.assertEqual(config.priority, 3)
        self.assertEqual(config.get_api_key(), "rotated-fake-key")

        list_response = self.client.get(self.list_url)
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)

        delete_response = self.client.delete(detail_url)
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ModelConfig.objects.filter(pk=config.pk).exists())

    def test_api_key_is_preserved_when_update_omits_it_and_cleared_when_blank(self) -> None:
        response = self.client.post(self.list_url, self.payload("key-lifecycle"), format="json")
        config = ModelConfig.objects.get(pk=response.data["id"])
        detail_url = reverse("configs:model-config-detail", args=(config.pk,))

        self.client.patch(detail_url, {"priority": 5}, format="json")
        config.refresh_from_db()
        self.assertEqual(config.get_api_key(), "fake-key-for-tests-only")

        cleared = self.client.patch(detail_url, {"api_key": ""}, format="json")
        self.assertEqual(cleared.status_code, status.HTTP_200_OK)
        config.refresh_from_db()
        self.assertEqual(config.get_api_key(), "")

    def test_only_one_default_is_retained_per_model_type(self) -> None:
        first = self.client.post(self.list_url, self.payload("first"), format="json")
        second = self.client.post(self.list_url, self.payload("second"), format="json")

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertFalse(ModelConfig.objects.get(name="first").is_default)
        self.assertTrue(ModelConfig.objects.get(name="second").is_default)

    def test_non_admin_and_anonymous_users_are_denied(self) -> None:
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_connection_endpoint_uses_adapter_and_default_fails_safely(self) -> None:
        created = self.client.post(self.list_url, self.payload("connection"), format="json")
        url = reverse("configs:model-config-test-connection", args=(created.data["id"],))

        unavailable = self.client.post(url)
        self.assertEqual(unavailable.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertFalse(unavailable.data["ok"])

        with patch.object(
            ModelConfigViewSet,
            "connection_tester",
            FakeSuccessfulConnectionTester(),
        ):
            connected = self.client.post(url)
        self.assertEqual(connected.status_code, status.HTTP_200_OK)
        self.assertEqual(connected.data["latency_ms"], 12)

    def test_usage_endpoint_aggregates_tokens_cost_and_outcomes(self) -> None:
        created = self.client.post(self.list_url, self.payload("usage"), format="json")
        config = ModelConfig.objects.get(pk=created.data["id"])
        ModelUsageRecord.objects.create(
            model_config=config,
            input_tokens=100,
            output_tokens=25,
            cost=Decimal("0.015"),
            success=True,
        )
        ModelUsageRecord.objects.create(
            model_config=config,
            input_tokens=10,
            output_tokens=5,
            cost=Decimal("0.002"),
            success=False,
        )

        response = self.client.get(
            reverse("configs:model-config-usage", args=(config.pk,))
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["calls"], 2)
        self.assertEqual(response.data["successful_calls"], 1)
        self.assertEqual(response.data["failed_calls"], 1)
        self.assertEqual(response.data["input_tokens"], 110)
        self.assertEqual(response.data["output_tokens"], 30)
        self.assertEqual(response.data["total_tokens"], 140)
        self.assertEqual(Decimal(response.data["cost"]), Decimal("0.017"))
