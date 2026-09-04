"""Root URL configuration for the platform backend."""

from django.contrib import admin
from django.urls import include, path

from config.views import health

urlpatterns = [
    path("", health, name="health"),
    path("api/health/", health, name="api-health"),
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.users.urls")),
    path("api/configs/", include("apps.configs.urls")),
    path("api/", include("apps.projects.urls")),
    path("api/", include("apps.agents.urls")),
]
