"""Remote server settings backed by PostgreSQL and Redis."""

import os

from config.settings.base import *  # noqa: F403
from config.settings.utils import get_required_env

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": get_required_env("POSTGRES_DB"),
        "USER": get_required_env("POSTGRES_USER"),
        "PASSWORD": get_required_env("POSTGRES_PASSWORD"),
        "HOST": get_required_env("POSTGRES_HOST"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"connect_timeout": 10},
    }
}

CELERY_BROKER_URL = get_required_env("REDIS_URL")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = False

SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

