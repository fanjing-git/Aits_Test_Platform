"""REST routes for test cases and execution runs."""

from rest_framework.routers import DefaultRouter

from apps.tests.views import TestCaseViewSet, TestRunViewSet

app_name = "tests"
router = DefaultRouter()
router.register("test-cases", TestCaseViewSet, basename="test-case")
router.register("test-runs", TestRunViewSet, basename="test-run")
urlpatterns = router.urls
