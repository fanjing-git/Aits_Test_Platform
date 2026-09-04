from rest_framework.routers import DefaultRouter

from apps.agents.views import AgentViewSet

router = DefaultRouter()
router.register("agents", AgentViewSet, basename="agent")

urlpatterns = router.urls
