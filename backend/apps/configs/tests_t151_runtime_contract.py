"""Focused tests for the shared model-call contract introduced by T151."""

from django.test import TestCase

from apps.configs.contracts import (
    ModelCapabilityError,
    model_call_contract,
    validate_model_capability,
)
from apps.configs.models import ModelConfig, ModelRoutingPolicy
from apps.configs.routing import ModelRouteResolver, required_model_types


class ModelRuntimeContractTests(TestCase):
    """Verify capability requirements are stable across route and call boundaries."""

    def make_config(self, name: str, model_type: str = ModelConfig.ModelType.CHAT) -> ModelConfig:
        return ModelConfig.objects.create(
            name=name,
            provider=ModelConfig.Provider.LOCAL,
            model_name=name,
            model_type=model_type,
        )

    def test_feature_contracts_define_input_output_and_capabilities(self) -> None:
        requirement = model_call_contract("requirement_analysis")
        screenshot = model_call_contract("screenshot")
        knowledge = model_call_contract("knowledge_model")
        embedding = model_call_contract(None, "retrieval")

        self.assertIn(ModelConfig.ModelType.CHAT, requirement.accepted_model_types)
        self.assertEqual(screenshot.input_mode, "text_and_image")
        self.assertEqual(knowledge.accepted_model_types, (ModelConfig.ModelType.EMBEDDING, ModelConfig.ModelType.RERANK))
        self.assertEqual(embedding.accepted_model_types, (ModelConfig.ModelType.EMBEDDING,))
        self.assertEqual(required_model_types("screenshot"), screenshot.accepted_model_types)

    def test_route_exposes_the_same_contract_used_for_capability_filtering(self) -> None:
        model = self.make_config("contract-chat")
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.REQUIREMENT_ANALYSIS,
            primary_model=model,
        )

        route = ModelRouteResolver().resolve(ModelRoutingPolicy.FeatureKey.REQUIREMENT_ANALYSIS)

        self.assertEqual(route.contract.capability, "text_structured")
        self.assertEqual(route.required_types, route.contract.accepted_model_types)

    def test_validation_rejects_inactive_or_wrong_capability(self) -> None:
        model = self.make_config("contract-embedding", ModelConfig.ModelType.EMBEDDING)
        with self.assertRaises(ModelCapabilityError) as raised:
            validate_model_capability(model, model_call_contract("requirement_analysis"))
        self.assertEqual(raised.exception.code, "model_capability_mismatch")

        model.is_active = False
        with self.assertRaises(ModelCapabilityError) as raised:
            validate_model_capability(model, model_call_contract("retrieval"))
        self.assertEqual(raised.exception.code, "model_inactive")
