"""Case generation REST routes."""

from rest_framework.routers import DefaultRouter

from apps.case_generation.views import CaseGenerationViewSet

router = DefaultRouter()
router.register("case-generation", CaseGenerationViewSet, basename="case-generation")

urlpatterns = router.urls
