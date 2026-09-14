"""Focused tests for safe first-deployment administrator bootstrap."""

import os
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.users.models import UserProfile

User = get_user_model()


class BootstrapPlatformAdminTests(TestCase):
    """Verify creation, idempotency, collision handling, and secret hygiene."""

    def test_creates_configured_admin_without_printing_password(self) -> None:
        """A fresh deployment creates the requested active administrator."""
        output = StringIO()
        with patch.dict(
            os.environ,
            {
                "AITS_BOOTSTRAP_ADMIN_USERNAME": "platform_admin",
                "AITS_BOOTSTRAP_ADMIN_PASSWORD": "Bootstrap-pass-123!",
            },
            clear=False,
        ):
            call_command("bootstrap_platform_admin", stdout=output)

        user = User.objects.get(username="platform_admin")
        self.assertTrue(user.is_active)
        self.assertEqual(user.profile.role, UserProfile.Role.ADMIN)
        self.assertTrue(user.check_password("Bootstrap-pass-123!"))
        self.assertNotIn("Bootstrap-pass-123!", output.getvalue())

    def test_bootstrapped_admin_can_login_and_access_admin_api(self) -> None:
        """The created administrator must authenticate through the real JWT API."""
        with patch.dict(
            os.environ,
            {
                "AITS_BOOTSTRAP_ADMIN_USERNAME": "platform_admin",
                "AITS_BOOTSTRAP_ADMIN_PASSWORD": "Bootstrap-pass-123!",
            },
            clear=False,
        ):
            call_command("bootstrap_platform_admin")

        login = self.client.post(
            "/api/auth/login/",
            {"account": "platform_admin", "password": "Bootstrap-pass-123!"},
            content_type="application/json",
        )
        self.assertEqual(login.status_code, 200)
        self.assertIn("access", login.json())

        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {login.json()['access']}"
        users = self.client.get("/api/auth/users/")
        self.assertEqual(users.status_code, 200)
        self.assertEqual(users.json()[0]["role"], UserProfile.Role.ADMIN)

    def test_first_run_api_creates_admin_and_closes_setup(self) -> None:
        """The public setup API is available once and rejects a second initialization."""
        status_before = self.client.get("/api/auth/bootstrap/status/")
        self.assertEqual(status_before.status_code, 200)
        self.assertTrue(status_before.json()["setup_required"])

        created = self.client.post(
            "/api/auth/bootstrap/",
            {
                "username": "first-run-admin",
                "password": "First-run-pass-123!",
                "password_confirm": "First-run-pass-123!",
            },
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertNotIn("password", created.json())

        status_after = self.client.get("/api/auth/bootstrap/status/")
        self.assertFalse(status_after.json()["setup_required"])
        duplicate = self.client.post(
            "/api/auth/bootstrap/",
            {
                "username": "second-admin",
                "password": "Second-pass-123!",
                "password_confirm": "Second-pass-123!",
            },
            content_type="application/json",
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_repeat_bootstrap_does_not_reset_password(self) -> None:
        """A later deployment is idempotent and preserves the existing password."""
        user = User.objects.create_user(username="platform_admin", password="Original-pass-123!")
        user.profile.role = UserProfile.Role.ADMIN
        user.profile.save(update_fields=("role",))

        with patch.dict(os.environ, {"AITS_BOOTSTRAP_ADMIN_PASSWORD": "New-pass-123!"}, clear=False):
            call_command("bootstrap_platform_admin", username="platform_admin")

        user.refresh_from_db()
        self.assertTrue(user.check_password("Original-pass-123!"))
        self.assertFalse(user.check_password("New-pass-123!"))

    def test_existing_non_admin_account_blocks_without_mutation(self) -> None:
        """A username collision cannot silently promote or reset the account."""
        user = User.objects.create_user(username="platform_admin", password="Original-pass-123!")

        with patch.dict(os.environ, {"AITS_BOOTSTRAP_ADMIN_PASSWORD": "New-pass-123!"}, clear=False):
            with self.assertRaises(CommandError):
                call_command("bootstrap_platform_admin", username="platform_admin")

        user.refresh_from_db()
        self.assertEqual(user.profile.role, UserProfile.Role.VIEWER)
        self.assertTrue(user.check_password("Original-pass-123!"))

    def test_first_bootstrap_requires_password_when_no_admin_exists(self) -> None:
        """A fresh deployment fails clearly instead of creating a guessable password."""
        with patch.dict(os.environ, {"AITS_BOOTSTRAP_ADMIN_PASSWORD": ""}, clear=False):
            with self.assertRaises(CommandError):
                call_command("bootstrap_platform_admin")

        self.assertFalse(User.objects.exists())

    def test_deployment_can_start_unconfigured_for_web_setup(self) -> None:
        """A fresh deployment can serve the setup page without a default password."""
        with patch.dict(os.environ, {"AITS_BOOTSTRAP_ADMIN_PASSWORD": ""}, clear=False):
            call_command("bootstrap_platform_admin", allow_unconfigured=True)

        self.assertFalse(User.objects.exists())

    def test_weak_bootstrap_password_is_rejected_without_creation(self) -> None:
        """Password policy failures do not leave a partial administrator behind."""
        with patch.dict(os.environ, {"AITS_BOOTSTRAP_ADMIN_PASSWORD": "password"}, clear=False):
            with self.assertRaises(CommandError):
                call_command("bootstrap_platform_admin")

        self.assertFalse(User.objects.exists())

    def test_existing_active_admin_allows_unconfigured_safe_start(self) -> None:
        """An old deployment can restart without credentials and without account changes."""
        user = User.objects.create_user(username="legacy-admin", password="Legacy-pass-123!")
        user.profile.role = UserProfile.Role.ADMIN
        user.profile.save(update_fields=("role",))

        with patch.dict(os.environ, {"AITS_BOOTSTRAP_ADMIN_PASSWORD": ""}, clear=False):
            call_command("bootstrap_platform_admin")

        self.assertEqual(User.objects.count(), 1)
