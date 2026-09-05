"""Environment REST routes."""
from rest_framework.routers import DefaultRouter
from apps.environments.views import EnvironmentViewSet

app_name = "environments"
router = DefaultRouter()
router.register("environments", EnvironmentViewSet, basename="environment")
urlpatterns = router.urls
