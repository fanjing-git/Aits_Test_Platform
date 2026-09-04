"""Routes for project and membership management."""

from rest_framework.routers import DefaultRouter

from apps.projects.views import ProjectViewSet

app_name = "projects"

router = DefaultRouter()
router.register("projects", ProjectViewSet, basename="project")

urlpatterns = router.urls
