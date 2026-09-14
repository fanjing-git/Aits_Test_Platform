"""Focused tests for the T154 unified route preflight contract."""

from django.test import TestCase

from apps.configs.models import ModelConfig, ModelRoutingPolicy
from apps.configs.routing import ModelRouteCapabilityError, ModelRouteResolver
from core.llm.manager import ModelManager, ModelNotFound


class T154UnifiedRoutingTests(TestCase):
    """Verify every model-consuming path sees the same explicit route."""

    def create_config(self, name: str, **overrides: object) -> ModelConfig:
        values: dict[str, object] = {
            "provider": ModelConfig.Provider.OPENAI,
            "model_name": name,
            "model_type": ModelConfig.ModelType.CHAT,
            "priority": 100,
        }
        values.update(overrides)
        return ModelConfig.objects.create(name=name, **values)

    def test_route_has_contract_candidates_and_safe_failure_diagnostic(self) -> None:
        route = ModelRouteResolver().resolve(ModelRoutingPolicy.FeatureKey.CASE_GENERATION)
        self.assertFalse(route.available)
        self.assertTrue(route.failure_reason)
        self.assertEqual(route.as_dict()["available"], False)
        self.assertEqual(route.as_dict()["candidates"], [])
        self.assertEqual(route.as_dict()["required_model_types"], ["chat", "multimodal", "vision"])

        model = self.create_config("t154-primary")
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.CASE_GENERATION,
            primary_model=model,
        )
        routed = ModelRouteResolver().resolve(ModelRoutingPolicy.FeatureKey.CASE_GENERATION)
        self.assertTrue(routed.available)
        self.assertEqual(routed.primary.source, "feature")
        self.assertEqual(routed.as_dict()["candidates"][0]["provider"], "openai")
        self.assertEqual(routed.as_dict()["failure_reason"], "")

    def test_active_model_without_route_is_not_implicit_fallback(self) -> None:
        self.create_config("t154-unbound")
        manager = ModelManager(lambda config: object())
        with self.assertRaises(ModelNotFound):
            manager.execute_routed(
                ModelRoutingPolicy.FeatureKey.CASE_GENERATION,
                lambda runtime, config: config.name,
            )

    def test_preferred_route_is_explicit_and_capability_checked(self) -> None:
        selected = self.create_config("t154-selected")
        route = ModelRouteResolver().resolve(
            ModelRoutingPolicy.FeatureKey.REQUIREMENT_ANALYSIS,
            preferred_name=selected.name,
        )
        self.assertEqual(route.primary.config, selected)
        self.assertEqual(route.primary.source, "operation")

        embedding = self.create_config(
            "t154-embedding",
            model_type=ModelConfig.ModelType.EMBEDDING,
        )
        with self.assertRaises(ModelRouteCapabilityError):
            ModelRouteResolver().resolve(
                ModelRoutingPolicy.FeatureKey.REQUIREMENT_ANALYSIS,
                preferred_name=embedding.name,
            )

    def test_backup_is_only_exposed_when_policy_allows_it(self) -> None:
        primary = self.create_config("t154-primary")
        backup = self.create_config("t154-backup", provider=ModelConfig.Provider.ANTHROPIC)
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.CASE_REVIEW,
            primary_model=primary,
            backup_model=backup,
            allow_fallback=True,
        )
        route = ModelRouteResolver().resolve(ModelRoutingPolicy.FeatureKey.CASE_REVIEW)
        self.assertEqual([item.config.name for item in route.candidates], [primary.name, backup.name])
        self.assertTrue(route.candidates[1].is_fallback)
        self.assertTrue(route.allow_fallback)
