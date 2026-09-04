"""Fernet helpers for encrypting secrets stored by the platform."""

import os

from cryptography.fernet import Fernet, InvalidToken
from django.core.exceptions import ImproperlyConfigured

MODEL_CONFIG_FERNET_KEY_ENV = "MODEL_CONFIG_FERNET_KEY"


class SecretDecryptionError(ValueError):
    """Indicate that encrypted data cannot be opened with the configured key."""


def _get_fernet() -> Fernet:
    """Build a Fernet instance from the required dedicated environment key."""
    key = os.environ.get(MODEL_CONFIG_FERNET_KEY_ENV, "").strip()
    if not key:
        raise ImproperlyConfigured(
            f"Required environment variable is missing: {MODEL_CONFIG_FERNET_KEY_ENV}"
        )
    try:
        return Fernet(key.encode("ascii"))
    except (UnicodeEncodeError, ValueError) as exc:
        raise ImproperlyConfigured(
            f"Environment variable is not a valid Fernet key: "
            f"{MODEL_CONFIG_FERNET_KEY_ENV}"
        ) from exc


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a non-empty secret without logging or otherwise exposing it."""
    if not isinstance(plaintext, str):
        raise TypeError("Secret plaintext must be a string.")
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a Fernet token and return a safe generic error on failure."""
    if not isinstance(ciphertext, str):
        raise TypeError("Encrypted secret must be a string.")
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise SecretDecryptionError(
            "Encrypted secret could not be decrypted with the configured key."
        ) from exc
