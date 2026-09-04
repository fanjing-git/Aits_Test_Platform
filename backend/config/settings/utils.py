"""Helpers shared by environment-specific settings modules."""

import os

from django.core.exceptions import ImproperlyConfigured


def get_required_env(name: str) -> str:
    """Return a non-empty environment variable or fail with a safe message."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"Required environment variable is missing: {name}")
    return value

