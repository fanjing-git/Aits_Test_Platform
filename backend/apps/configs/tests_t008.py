"""Encryption tests for task T008."""

import os
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.test import TestCase

from apps.configs.models import ModelConfig
from core.utils.crypto import (
    MODEL_CONFIG_FERNET_KEY_ENV,
    SecretDecryptionError,
    decrypt_secret,
    encrypt_secret,
)


class ModelConfigEncryptionTests(TestCase):
    """Verify API keys are encrypted at rest and fail safely."""

    def setUp(self) -> None:
        """Generate isolated non-production keys for each test."""
        self.fernet_key = Fernet.generate_key().decode("ascii")
        self.environment = patch.dict(
            os.environ,
            {MODEL_CONFIG_FERNET_KEY_ENV: self.fernet_key},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def build_config(self, name: str = "encrypted-model") -> ModelConfig:
        """Build a valid unsaved configuration for encryption tests."""
        return ModelConfig(
            name=name,
            provider=ModelConfig.Provider.OPENAI,
            model_name="secure-model",
        )

    def test_api_key_round_trip_stores_only_ciphertext(self) -> None:
        """The database value must differ from and not contain the plaintext key."""
        plaintext = "test-api-key-not-a-real-secret"
        config = self.build_config()
        config.set_api_key(plaintext)
        config.save()

        stored = ModelConfig.objects.get(pk=config.pk)
        self.assertNotEqual(stored.api_key_encrypted, plaintext)
        self.assertNotIn(plaintext, stored.api_key_encrypted)
        self.assertEqual(stored.get_api_key(), plaintext)

    def test_direct_plaintext_storage_is_rejected(self) -> None:
        """Callers must not bypass the encryption method with raw credentials."""
        config = self.build_config("plaintext-rejected")
        config.api_key_encrypted = "plain-api-key"

        with self.assertRaises(ValidationError):
            config.save()
        self.assertFalse(ModelConfig.objects.filter(name=config.name).exists())

    def test_empty_api_key_is_supported_for_local_models(self) -> None:
        """Providers without credentials should persist an empty value safely."""
        config = self.build_config("no-key-model")
        config.set_api_key("")
        config.save()

        self.assertEqual(config.api_key_encrypted, "")
        self.assertEqual(config.get_api_key(), "")

    def test_wrong_key_returns_a_generic_decryption_error(self) -> None:
        """Key mismatch must fail without including ciphertext or plaintext."""
        ciphertext = encrypt_secret("sensitive-test-value")
        wrong_key = Fernet.generate_key().decode("ascii")

        with patch.dict(os.environ, {MODEL_CONFIG_FERNET_KEY_ENV: wrong_key}):
            with self.assertRaisesRegex(
                SecretDecryptionError,
                "could not be decrypted",
            ):
                decrypt_secret(ciphertext)

    def test_missing_or_invalid_key_fails_configuration_safely(self) -> None:
        """Missing and malformed environment keys must never use a fallback."""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                ImproperlyConfigured,
                MODEL_CONFIG_FERNET_KEY_ENV,
            ):
                encrypt_secret("test-value")

        with patch.dict(os.environ, {MODEL_CONFIG_FERNET_KEY_ENV: "invalid"}):
            with self.assertRaisesRegex(
                ImproperlyConfigured,
                MODEL_CONFIG_FERNET_KEY_ENV,
            ):
                encrypt_secret("test-value")
