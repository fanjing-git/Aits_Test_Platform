"""Model tests for task T007."""

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.configs.models import ModelConfig


class ModelConfigTests(TestCase):
    """Verify model configuration persistence, defaults, and validation."""

    def test_multiple_model_configs_can_be_created_and_ordered(self) -> None:
        """Different providers should coexist and follow routing priority."""
        slower = ModelConfig.objects.create(
            name="primary-openai",
            provider=ModelConfig.Provider.OPENAI,
            model_name="gpt-model",
            priority=20,
        )
        faster = ModelConfig.objects.create(
            name="fallback-deepseek",
            provider=ModelConfig.Provider.DEEPSEEK,
            model_name="deepseek-model",
            priority=10,
        )

        self.assertEqual(list(ModelConfig.objects.all()), [faster, slower])

    def test_defaults_are_safe_and_do_not_contain_plaintext_credentials(self) -> None:
        """A new configuration should start active with empty credential storage."""
        config = ModelConfig.objects.create(
            name="local-model",
            provider=ModelConfig.Provider.LOCAL,
            model_name="local-chat",
        )

        self.assertEqual(config.model_type, ModelConfig.ModelType.CHAT)
        self.assertEqual(config.api_key_encrypted, "")
        self.assertEqual(config.parameters, {})
        self.assertFalse(config.is_default)
        self.assertTrue(config.is_active)
        self.assertEqual(config.priority, 100)

    def test_parameters_reject_non_object_json(self) -> None:
        """Routing parameters should reject ambiguous top-level arrays."""
        config = ModelConfig(
            name="invalid-parameters",
            provider=ModelConfig.Provider.CUSTOM,
            model_name="custom-model",
            parameters=["unexpected-list"],
        )

        with self.assertRaises(ValidationError):
            config.full_clean()

    def test_invalid_provider_model_type_and_url_are_rejected(self) -> None:
        """Choice and URL fields should enforce the declared model contract."""
        config = ModelConfig(
            name="invalid-fields",
            provider="unknown",
            model_name="unknown-model",
            model_type="unknown",
            api_base_url="not-a-url",
        )

        with self.assertRaises(ValidationError):
            config.full_clean()
