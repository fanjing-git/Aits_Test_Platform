"""Celery application shared by workers and Django."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("ai_agent_test_platform")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

