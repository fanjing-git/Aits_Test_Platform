"""Focused regression tests for T159 call observability and diagnostics."""

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.configs.models import ModelCallRecord, ModelConfig, ModelRoutingPolicy
from apps.users.models import UserProfile
from core.llm.manager import ModelManager


class FakeRuntime:
    """Small runtime double that never contacts a provider."""

    def __init__(self, name: str) -> None:
        self.name = name


class T159ObservabilityTests(APITestCase):
    """Verify success, fallback, blocked, and permission-safe diagnostics."""

    def setUp(self) -> None:
        self.admin = get_user_model().objects.create_user(username="t159-admin")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save(update_fields=("role",))
        self.viewer = get_user_model().objects.create_user(username="t159-viewer")

    def create_config(self, name: str, **overrides: object) -> ModelConfig:
        values: dict[str, object] = {
            "provider": ModelConfig.Provider.LOCAL,
            "model_name": name,
            "model_type": ModelConfig.ModelType.CHAT,
            "priority": 100,
        }
        values.update(overrides)
        return ModelConfig.objects.create(name=name, **values)

    @staticmethod
    def factory(config: ModelConfig) -> FakeRuntime:
        return FakeRuntime(config.name)

    def test_success_and_fallback_share_request_id_without_sensitive_payload(self) -> None:
        primary = self.create_config("t159-primary", priority=1)
        backup = self.create_config("t159-backup", priority=2)
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.CASE_REVIEW,
            primary_model=primary,
            backup_model=backup,
            allow_fallback=True,
        )
        manager = ModelManager(self.factory)

        result = manager.execute_routed(
            ModelRoutingPolicy.FeatureKey.CASE_REVIEW,
            lambda runtime, config: runtime.name
            if config.name == backup.name
            else (_ for _ in ()).throw(TimeoutError("provider payload must not persist")),
        )

        self.assertEqual(result, "t159-backup")
        records = list(ModelCallRecord.objects.order_by("created_at"))
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].status, ModelCallRecord.Status.FAILED)
        self.assertEqual(records[1].status, ModelCallRecord.Status.COMPLETED)
        self.assertEqual(records[0].request_id, records[1].request_id)
        self.assertTrue(records[0].retryable)
        self.assertNotIn("provider payload", str(records[0].trace))
        self.assertNotIn("api_key", str(records[0].trace).lower())

    def test_route_block_is_recorded_without_provider_attempt(self) -> None:
        manager = ModelManager(self.factory)
        with self.assertRaises(Exception):
            manager.execute_routed(
                ModelRoutingPolicy.FeatureKey.CASE_GENERATION,
                lambda runtime, config: config.name,
            )
        record = ModelCallRecord.objects.get()
        self.assertEqual(record.status, ModelCallRecord.Status.BLOCKED)
        self.assertEqual(record.failure_stage, "route_resolution")
        self.assertEqual(record.provider, "")
        self.assertIn("No provider call", record.cost_hint)

    def test_legacy_fallback_failures_are_recorded(self) -> None:
        self.create_config("t159-legacy")
        manager = ModelManager(self.factory)
        with self.assertRaises(Exception):
            manager.execute_with_fallback(
                "chat",
                lambda runtime, config: (_ for _ in ()).throw(TimeoutError("not persisted")),
            )
        record = ModelCallRecord.objects.get()
        self.assertEqual(record.route_source, "legacy_fallback")
        self.assertEqual(record.status, ModelCallRecord.Status.FAILED)
        self.assertEqual(record.error_code, "timeouterror")
        self.assertTrue(record.retryable)

    def test_diagnostics_endpoint_is_admin_only_and_filters_safe_fields(self) -> None:
        config = self.create_config("t159-api")
        ModelCallRecord.objects.create(
            feature_key="case_generation",
            task_type="case_gen",
            model_config=config,
            provider=config.provider,
            model_name=config.model_name,
            model_type=config.model_type,
            route_source="feature",
            status=ModelCallRecord.Status.COMPLETED,
            duration_ms=42,
            trace=[{"stage": "model_call", "event": "completed"}],
        )
        url = reverse("configs:model-config-call-records")

        self.client.force_authenticate(self.admin)
        response = self.client.get(url, {"feature_key": "case_generation", "limit": 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["duration_ms"], 42)
        self.assertNotIn("api_key", response.data[0])
        self.assertNotIn("input_text", response.data[0])

        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_401_UNAUTHORIZED)
