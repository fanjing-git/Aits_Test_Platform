from rest_framework.routers import DefaultRouter

from apps.agents.views import AgentViewSet
from apps.agents.execution_views import AgentExecutionViewSet

router = DefaultRouter()
router.register("agents", AgentViewSet, basename="agent")
router.register("agent-executions", AgentExecutionViewSet, basename="agent-execution")

urlpatterns = router.urls
