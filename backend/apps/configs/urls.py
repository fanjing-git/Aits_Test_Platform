"""Routes for model configuration management."""

from rest_framework.routers import DefaultRouter

from apps.configs.views import ModelConfigViewSet, PromptConfigViewSet

app_name = "configs"

router = DefaultRouter()
router.register("models", ModelConfigViewSet, basename="model-config")
router.register("prompts", PromptConfigViewSet, basename="prompt-config")

urlpatterns = router.urls
