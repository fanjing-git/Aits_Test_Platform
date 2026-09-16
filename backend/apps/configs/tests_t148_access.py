"""Focused tests for the explicit user access entrypoint contract."""

from unittest.mock import patch
from urllib.error import URLError

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.configs.deployment import (
    DeploymentAccessError,
    DeploymentAccessService,
    classify_access_scope,
    normalize_access_url,
)
from apps.users.models import UserProfile

User = get_user_model()


class DeploymentAccessServiceTests(SimpleTestCase):
    """Verify URL safety, scope classification and no-redirect probing."""

    def test_normalization_rejects_credentials_query_and_non_http_urls(self) -> None:
        for value in (
            "https://user:secret@example.com",
            "https://example.com/?token=secret",
            "ftp://example.com",
        ):
            with self.subTest(value=value), self.assertRaises(DeploymentAccessError):
                normalize_access_url(value)

    def test_scope_does_not_enumerate_or_resolve_hosts(self) -> None:
        self.assertEqual(classify_access_scope("http://127.0.0.1:5173"), "private")
        self.assertEqual(classify_access_scope("http://10.0.0.8:8090"), "private")
        self.assertEqual(classify_access_scope("https://share.example.com"), "public")

    @override_settings(PUBLIC_APP_URL="https://share.example.com/aits")
    def test_health_probe_uses_explicit_same_origin_health_path_without_credentials(self) -> None:
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        class Opener:
            def open(self, request, timeout: int):
                self.request = request
                self.timeout = timeout
                return Response()

        opener = Opener()
        with patch("apps.configs.deployment.build_opener", return_value=opener):
            result = DeploymentAccessService.check()
        self.assertEqual(result["health_status"], "healthy")
        self.assertEqual(result["health_check_url"], "https://share.example.com/aits/api/health/")
        self.assertEqual(opener.timeout, 3)
        self.assertNotIn("Authorization", opener.request.headers)

    @override_settings(PUBLIC_APP_URL="https://share.example.com")
    def test_health_probe_reports_unreachable_without_exposing_exception_details(self) -> None:
        with patch("apps.configs.deployment.build_opener") as build_opener:
            build_opener.return_value.open.side_effect = URLError("private-host-secret")
            result = DeploymentAccessService.check()
        self.assertEqual(result["health_status"], "unreachable")
        self.assertNotIn("private-host-secret", result["health_message"])


class DeploymentAccessApiTests(APITestCase):
    """Verify administrator-only metadata, checks and invitation URL compatibility."""

    def setUp(self) -> None:
        self.admin = User.objects.create_user(username="access-admin", password="Admin-pass-123!")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save(update_fields=("role",))
        self.viewer = User.objects.create_user(username="access-viewer", password="Viewer-pass-123!")
        self.url = "/api/configs/deployment-access/"

    @override_settings(PUBLIC_APP_URL="https://share.example.com")
    def test_admin_reads_and_checks_explicit_entrypoint(self) -> None:
        self.client.force_authenticate(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["app_url"], "https://share.example.com")
        self.assertEqual(response.data["tls_status"], "enabled")
        self.assertEqual(response.data["access_scope"], "public")

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        with patch("apps.configs.deployment.build_opener") as build_opener:
            build_opener.return_value.open.return_value = Response()
            checked = self.client.post(f"{self.url}check/")
        self.assertEqual(checked.status_code, status.HTTP_200_OK)
        self.assertEqual(checked.data["health_status"], "healthy")
        self.assertIsNotNone(checked.data["last_checked_at"])

    @override_settings(PUBLIC_APP_URL="")
    def test_unconfigured_entrypoint_is_explicit_and_does_not_guess_ip(self) -> None:
        self.client.force_authenticate(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["configured"])
        self.assertEqual(response.data["app_url"], "")
        self.assertIn("PUBLIC_APP_URL", response.data["health_message"])

    @override_settings(PUBLIC_APP_URL="ftp://internal.example")
    def test_invalid_entrypoint_is_rejected_without_guessing_a_replacement(self) -> None:
        self.client.force_authenticate(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "invalid_public_app_url")

    def test_viewer_and_anonymous_user_are_denied(self) -> None:
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(PUBLIC_APP_URL="https://share.example.com")
    def test_invitation_returns_configured_share_url_and_legacy_path(self) -> None:
        self.client.force_authenticate(self.admin)
        response = self.client.post(self.url.replace("/api/configs/deployment-access/", "/api/auth/users/"), {"account": "share-colleague"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["activation_url"].startswith("https://share.example.com/activate?token="))
        self.assertTrue(response.data["activation_path"].startswith("/activate?token="))
