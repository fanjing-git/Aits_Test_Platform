"""Shared safety limits for requirement document sources."""

from __future__ import annotations

from django.conf import settings


DEFAULT_REQUIREMENT_DOCUMENT_MAX_BYTES = 10 * 1024 * 1024


def requirement_document_max_bytes() -> int:
    """Return the configured requirement document byte limit."""
    raw_value = getattr(
        settings,
        "REQUIREMENT_DOCUMENT_MAX_BYTES",
        DEFAULT_REQUIREMENT_DOCUMENT_MAX_BYTES,
    )
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = DEFAULT_REQUIREMENT_DOCUMENT_MAX_BYTES
    return max(1, value)


def requirement_document_limit_label() -> str:
    """Return a compact Chinese label for the configured document limit."""
    megabytes = requirement_document_max_bytes() / (1024 * 1024)
    if megabytes.is_integer():
        return f"{int(megabytes)}MB"
    return f"{megabytes:.1f}MB"


__all__ = [
    "DEFAULT_REQUIREMENT_DOCUMENT_MAX_BYTES",
    "requirement_document_limit_label",
    "requirement_document_max_bytes",
]
