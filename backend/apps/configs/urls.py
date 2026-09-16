"""Routes for model configuration management."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.configs.views import DeploymentAccessView, ModelConfigViewSet, ModelRoutingPolicyViewSet, PromptConfigViewSet

app_name = "configs"

router = DefaultRouter()
router.register("models", ModelConfigViewSet, basename="model-config")
router.register("routing-policies", ModelRoutingPolicyViewSet, basename="routing-policy")
router.register("prompts", PromptConfigViewSet, basename="prompt-config")

urlpatterns = [
    path("deployment-access/", DeploymentAccessView.as_view(), name="deployment-access"),
    path("deployment-access/check/", DeploymentAccessView.as_view(), name="deployment-access-check"),
    *router.urls,
]
