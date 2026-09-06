"""Settings shared by all runtime environments."""

import os
from pathlib import Path

from config.settings.utils import get_required_env

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = get_required_env("DJANGO_SECRET_KEY")
DEBUG = False

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.users.apps.UsersConfig",
    "apps.configs.apps.ConfigsConfig",
    "apps.projects.apps.ProjectsConfig",
    "apps.agents.apps.AgentsConfig",
    "apps.environments.apps.EnvironmentsConfig",
    "apps.knowledge.apps.KnowledgeConfig",
    "apps.skills.apps.SkillsConfig",
    "apps.requirement_analysis.apps.RequirementAnalysisConfig",
    "apps.case_generation.apps.CaseGenerationConfig",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_IMPORTS = ("config.tasks",)

# Exact trusted origins for environment health probes; no wildcard targets.
ENVIRONMENT_HEALTH_ALLOWED_ORIGINS = tuple(value.strip() for value in os.environ.get("ENVIRONMENT_HEALTH_ALLOWED_ORIGINS", "http://127.0.0.1:8000").split(",") if value.strip())

CELERY_BEAT_SCHEDULE = {
    "environments-check-all-health": {
        "task": "environments.check_all_health",
        "schedule": 300.0,
    },
}

KNOWLEDGE_DOCUMENT_ROOT = Path(os.environ.get("KNOWLEDGE_DOCUMENT_ROOT", BASE_DIR / ".runtime" / "knowledge-documents"))
KNOWLEDGE_DOCUMENT_MAX_BYTES = int(os.environ.get("KNOWLEDGE_DOCUMENT_MAX_BYTES", 10 * 1024 * 1024))
KNOWLEDGE_CHUNK_SIZE = int(os.environ.get("KNOWLEDGE_CHUNK_SIZE", 500))
KNOWLEDGE_CHUNK_OVERLAP = int(os.environ.get("KNOWLEDGE_CHUNK_OVERLAP", 50))
REQUIREMENT_DOCUMENT_ROOT = Path(os.environ.get("REQUIREMENT_DOCUMENT_ROOT", BASE_DIR / ".runtime" / "requirement-documents"))
REQUIREMENT_DOCUMENT_MAX_BYTES = int(os.environ.get("REQUIREMENT_DOCUMENT_MAX_BYTES", 10 * 1024 * 1024))
