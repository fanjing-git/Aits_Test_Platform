"""Encrypted object storage for environment credentials and variables."""
import json
from typing import Any
from django.core.exceptions import ValidationError
from django.db import models
from core.utils.crypto import decrypt_secret, encrypt_secret


class EncryptedObjectField(models.JSONField):
    """Expose a JSON object in Python and store only an encrypted JSON string.

    Nested database lookups are not supported; load the owning environment
    before accessing configuration values.
    """

    def get_prep_value(self, value: Any) -> str:
        """Encrypt every ORM write, including bulk creates and updates."""
        if not isinstance(value, dict):
            raise ValidationError("环境配置必须是 JSON 对象。")
        try:
            plaintext = json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValidationError("环境配置必须包含有效的 JSON 数据。") from exc
        return encrypt_secret(plaintext)

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> Any:
        """Decrypt a persisted object without exposing it in error messages."""
        ciphertext = super().from_db_value(value, expression, connection)
        if ciphertext is None:
            return None
        result = json.loads(decrypt_secret(ciphertext))
        if not isinstance(result, dict):
            raise ValidationError("环境配置必须是 JSON 对象。")
        return result

    def get_transform(self, name: str) -> Any:
        """Reject JSON key queries because the stored payload is encrypted."""
        raise TypeError("Encrypted environment configurations do not support key lookups.")
