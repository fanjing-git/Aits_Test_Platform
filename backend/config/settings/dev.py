"""Local development settings without external infrastructure dependencies."""

import os

from config.settings.base import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}

CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

PUBLIC_APP_URL = os.environ.get("PUBLIC_APP_URL", "http://127.0.0.1:5173").strip()
PUBLIC_API_URL = os.environ.get("PUBLIC_API_URL", "").strip()
