"""Local development settings without external infrastructure dependencies."""

import os

from config.settings.base import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}

_queue_enabled = os.environ.get("AITS_CELERY_QUEUE_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
_queue_root = BASE_DIR.parent / ".runtime" / "celery"
_queue_root.mkdir(parents=True, exist_ok=True)
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "filesystem://") if _queue_enabled else "memory://"
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "cache+memory://")
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "data_folder_in": str(_queue_root),
    "data_folder_out": str(_queue_root),
    "data_folder_processed": str(_queue_root / "processed"),
} if _queue_enabled else {}
CELERY_TASK_ALWAYS_EAGER = not _queue_enabled
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_ACKS_LATE = _queue_enabled
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

PUBLIC_APP_URL = os.environ.get("PUBLIC_APP_URL", "http://127.0.0.1:5173").strip()
PUBLIC_API_URL = os.environ.get("PUBLIC_API_URL", "").strip()
