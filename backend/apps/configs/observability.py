"""Safe persistence helpers for model-call diagnostics."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any

from django.utils import timezone

from apps.configs.models import ModelCallRecord, ModelConfig


_SAFE_CODE = re.compile(r"[^a-z0-9_.-]+")
_RETRYABLE_ERRORS = (TimeoutError, ConnectionError, OSError)


class ModelCallObservability:
    """Write bounded diagnostics without allowing provider data into the database."""

    @staticmethod
    def new_request_id() -> str:
        """Return a correlation ID that is safe to expose to an operator."""
        return str(uuid.uuid4())

    @classmethod
    def start(
        cls,
        *,
        feature_key: str,
        task_type: str | None,
        config: ModelConfig,
        route_source: str,
        is_fallback: bool,
        request_id: str,
    ) -> ModelCallRecord | None:
        """Persist a started attempt, returning None if diagnostics are unavailable."""
        try:
            return ModelCallRecord.objects.create(
                request_id=request_id,
                feature_key=str(feature_key),
                task_type=task_type or "",
                model_config=config,
                provider=str(config.provider),
                model_name=config.model_name,
                model_type=str(config.model_type),
                route_source=route_source,
                is_fallback=is_fallback,
                status=ModelCallRecord.Status.STARTED,
                trace=[
                    {
                        "stage": "preflight",
                        "event": "route_resolved",
                        "feature_key": str(feature_key),
                        "route_source": route_source,
                    }
                ],
            )
        except Exception:
            return None

    @classmethod
    def complete(
        cls,
        record: ModelCallRecord | None,
        *,
        duration_ms: int,
    ) -> None:
        """Mark an attempt successful without recording its input or output."""
        if record is None:
            return
        cls._update(
            record,
            status=ModelCallRecord.Status.COMPLETED,
            duration_ms=max(0, duration_ms),
            finished_at=timezone.now(),
            trace=cls._append_trace(record.trace, "completed", "model_call"),
            cost_hint="Runtime did not report token cost.",
        )

    @classmethod
    def fail(
        cls,
        record: ModelCallRecord | None,
        error: Exception,
        *,
        duration_ms: int,
        failure_stage: str = "runtime",
    ) -> None:
        """Mark an attempt failed with a stable code and no provider message."""
        if record is None:
            return
        error_code = cls._error_code(error)
        retryable = bool(getattr(error, "retryable", False)) or isinstance(
            error, _RETRYABLE_ERRORS
        )
        cls._update(
            record,
            status=ModelCallRecord.Status.FAILED,
            failure_stage=failure_stage,
            error_code=error_code,
            retryable=retryable,
            duration_ms=max(0, duration_ms),
            finished_at=timezone.now(),
            trace=cls._append_trace(record.trace, "failed", failure_stage),
            cost_hint="Cost is unknown; no usage report was received.",
        )

    @classmethod
    def blocked(
        cls,
        *,
        feature_key: str,
        task_type: str | None,
        request_id: str,
        error_code: str,
        failure_stage: str,
        trace: list[dict[str, Any]] | None = None,
    ) -> None:
        """Persist a preflight block when no model attempt was allowed."""
        try:
            ModelCallRecord.objects.create(
                request_id=request_id,
                feature_key=str(feature_key),
                task_type=task_type or "",
                stage="preflight",
                status=ModelCallRecord.Status.BLOCKED,
                failure_stage=failure_stage,
                error_code=cls._normalize_code(error_code),
                retryable=False,
                finished_at=timezone.now(),
                cost_hint="No provider call was made; no cost was incurred.",
                trace=cls._bounded_trace(trace or [])
                + [{"stage": failure_stage, "event": "blocked"}],
            )
        except Exception:
            return

    @staticmethod
    def _update(record: ModelCallRecord, **values: Any) -> None:
        """Update one record defensively so observability never breaks business flow."""
        try:
            for field, value in values.items():
                setattr(record, field, value)
            record.save(update_fields=[*values.keys()])
        except Exception:
            return

    @classmethod
    def _error_code(cls, error: Exception) -> str:
        """Prefer a provider-neutral code attribute and otherwise use the class name."""
        return cls._normalize_code(str(getattr(error, "code", "")) or error.__class__.__name__)

    @staticmethod
    def _normalize_code(value: str) -> str:
        """Keep error identifiers short and free of messages or credentials."""
        normalized = _SAFE_CODE.sub("_", str(value).strip().lower()).strip("_.-")
        return normalized[:80] or "model_call_failed"

    @classmethod
    def _append_trace(
        cls,
        trace: Any,
        event: str,
        stage: str,
    ) -> list[dict[str, Any]]:
        """Append a small lifecycle event to an existing bounded trace."""
        values = cls._bounded_trace(trace)
        values.append({"stage": stage, "event": event})
        return values

    @staticmethod
    def _bounded_trace(trace: Any) -> list[dict[str, Any]]:
        """Keep only JSON-like trace entries and prevent unbounded growth."""
        if not isinstance(trace, list):
            return []
        safe: list[dict[str, Any]] = []
        for item in trace[-19:]:
            if isinstance(item, Mapping):
                safe.append(
                    {
                        str(key)[:40]: str(value)[:160]
                        for key, value in item.items()
                        if str(key).lower() not in {"input", "prompt", "content", "body", "response"}
                    }
                )
        return safe
