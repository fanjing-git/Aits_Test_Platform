"""Tests for the minimal project-level health endpoint."""

from django.test import Client, RequestFactory, SimpleTestCase

from config.views import health


class HealthViewUnitTests(SimpleTestCase):
    """Validate the health view independently from URL routing."""

    def test_health_view_returns_success_payload(self) -> None:
        """The health view should return the stable service status payload."""
        request = RequestFactory().get("/")

        response = health(request)

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {"status": "ok", "service": "ai-agent-test-platform"},
        )


class HealthEndpointIntegrationTests(SimpleTestCase):
    """Validate URL routing and response serialization together."""

    def test_root_route_exposes_health_endpoint(self) -> None:
        """A request to the root URL should reach the health view."""
        response = Client().get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

