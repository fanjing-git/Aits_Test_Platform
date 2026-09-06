"""Requirement analysis REST routes."""

from rest_framework.routers import DefaultRouter

from apps.requirement_analysis.views import RequirementAnalysisViewSet, RequirementDocumentViewSet

router = DefaultRouter()
router.register("requirement-documents", RequirementDocumentViewSet, basename="requirement-document")
router.register("requirement-analyses", RequirementAnalysisViewSet, basename="requirement-analysis")

urlpatterns = router.urls
