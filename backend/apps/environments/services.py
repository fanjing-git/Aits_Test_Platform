"""Transactional environment configuration persistence."""
from typing import Any
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError
from apps.environments.models import Environment


def save_environment(values: dict[str, Any], instance: Environment | None = None) -> Environment:
    """Merge patches under a row lock and normalize model/uniqueness errors."""
    try:
        with transaction.atomic():
            environment = Environment.objects.select_for_update().get(pk=instance.pk) if instance else Environment()
            if instance and any(key in values and values[key] != getattr(environment, key) for key in ("base_url", "health_check_url")):
                environment.health_status = Environment.HealthStatus.UNKNOWN
                environment.health_checked_at = None
                environment.health_message = ""
                environment.health_latency_ms = None
                if environment.status != Environment.Status.MAINTENANCE:
                    environment.status = Environment.Status.UNAVAILABLE
            for name, value in values.items():
                setattr(environment, name, value)
            environment.save()
            return environment
    except ModelValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}) from exc
    except IntegrityError as exc:
        raise ValidationError({"name": "该项目已配置此类型环境。"}) from exc
