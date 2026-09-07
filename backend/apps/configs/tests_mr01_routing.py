"""Focused tests for MR-01 platform and feature model routing."""

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.configs.models import ModelConfig, ModelRoutingPolicy
from apps.configs.routing import ModelRouteCapabilityError, ModelRouteResolver
from core.llm.manager import ModelFallbackExhausted, ModelManager


class FakeRuntime:
    """Small runtime double that never contacts a provider."""

    def __init__(self, name: str) -> None:
        self.name = name


class ModelRoutingPolicyTests(TestCase):
    """Verify precedence, capability gates, and explicit fallback semantics."""

    def create_config(self, name: str, **overrides: object) -> ModelConfig:
        values: dict[str, object] = {
            "provider": ModelConfig.Provider.LOCAL,
            "model_name": name,
            "model_type": ModelConfig.ModelType.CHAT,
            "priority": 100,
        }
        values.update(overrides)
        return ModelConfig.objects.create(name=name, **values)

    def test_feature_policy_overrides_global_and_operation_overrides_feature(self) -> None:
        global_model = self.create_config("global")
        feature_model = self.create_config("feature")
        operation_model = self.create_config("operation")
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.GLOBAL,
            primary_model=global_model,
        )
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.CASE_GENERATION,
            primary_model=feature_model,
        )

        resolver = ModelRouteResolver()
        feature_route = resolver.resolve(ModelRoutingPolicy.FeatureKey.CASE_GENERATION)
        operation_route = resolver.resolve(
            ModelRoutingPolicy.FeatureKey.CASE_GENERATION,
            preferred_name=operation_model.name,
        )

        self.assertEqual(feature_route.primary.config, feature_model)
        self.assertEqual(feature_route.primary.source, "feature")
        self.assertEqual(operation_route.primary.config, operation_model)
        self.assertEqual(operation_route.primary.source, "operation")

    def test_global_model_must_match_feature_capability(self) -> None:
        vision = self.create_config(
            "text-only-global",
            model_type=ModelConfig.ModelType.CHAT,
        )
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.GLOBAL,
            primary_model=vision,
        )

        with self.assertRaises(ModelRouteCapabilityError):
            ModelRouteResolver().resolve(ModelRoutingPolicy.FeatureKey.SCREENSHOT_ANALYSIS)

    def test_feature_binding_can_override_incompatible_global_model(self) -> None:
        global_model = self.create_config("text-global")
        vision_model = self.create_config(
            "vision-feature",
            model_type=ModelConfig.ModelType.VISION,
        )
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.GLOBAL,
            primary_model=global_model,
        )
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.SCREENSHOT_ANALYSIS,
            primary_model=vision_model,
        )

        route = ModelRouteResolver().resolve(ModelRoutingPolicy.FeatureKey.SCREENSHOT_ANALYSIS)

        self.assertEqual(route.primary.config, vision_model)

    def test_backup_is_not_used_without_explicit_policy(self) -> None:
        primary = self.create_config("primary")
        backup = self.create_config("backup")
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.CASE_REVIEW,
            primary_model=primary,
            backup_model=backup,
        )
        route = ModelRouteResolver().resolve(ModelRoutingPolicy.FeatureKey.CASE_REVIEW)
        self.assertEqual([item.config.name for item in route.candidates], ["primary"])
        self.assertFalse(route.allow_fallback)

    def test_enabled_backup_is_available_to_routed_executor(self) -> None:
        primary = self.create_config("primary")
        backup = self.create_config("backup")
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.CASE_REVIEW,
            primary_model=primary,
            backup_model=backup,
            allow_fallback=True,
        )
        manager = ModelManager(lambda config: FakeRuntime(config.name))

        result = manager.execute_routed(
            ModelRoutingPolicy.FeatureKey.CASE_REVIEW,
            lambda runtime, config: runtime.name if config.name == "backup" else (_ for _ in ()).throw(TimeoutError()),
        )

        self.assertEqual(result, "backup")

    def test_routed_executor_does_not_silently_try_backup(self) -> None:
        primary = self.create_config("primary")
        backup = self.create_config("backup")
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.CASE_REVIEW,
            primary_model=primary,
            backup_model=backup,
        )
        manager = ModelManager(lambda config: FakeRuntime(config.name))

        with self.assertRaises(ModelFallbackExhausted) as raised:
            manager.execute_routed(
                ModelRoutingPolicy.FeatureKey.CASE_REVIEW,
                lambda runtime, config: (_ for _ in ()).throw(TimeoutError("provider")),
            )

        self.assertEqual(raised.exception.attempted_models, ("primary",))

    def test_policy_rejects_same_primary_and_backup(self) -> None:
        config = self.create_config("same")
        policy = ModelRoutingPolicy(
            feature_key=ModelRoutingPolicy.FeatureKey.GLOBAL,
            primary_model=config,
            backup_model=config,
        )
        with self.assertRaises(ValidationError):
            policy.full_clean()
