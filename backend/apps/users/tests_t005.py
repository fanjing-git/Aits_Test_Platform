"""API tests for registration and JWT authentication."""

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.models import UserProfile


class AuthenticationApiTests(APITestCase):
    """Verify the registration, login, refresh, and current-user flow."""

    def setUp(self) -> None:
        """Define stable endpoints and test credentials."""
        self.register_url = reverse("users:register")
        self.login_url = reverse("users:login")
        self.refresh_url = reverse("users:token-refresh")
        self.me_url = reverse("users:current-user")
        self.credentials = {
            "username": "api-tester",
            "email": "tester@example.com",
            "password": "Strong-Test-Password-2026!",
            "password_confirm": "Strong-Test-Password-2026!",
        }

    def test_registration_hashes_password_and_assigns_viewer_role(self) -> None:
        """Registration must not persist plaintext or grant a privileged role."""
        response = self.client.post(self.register_url, self.credentials, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = get_user_model().objects.get(username="api-tester")
        self.assertTrue(user.check_password(self.credentials["password"]))
        self.assertNotEqual(user.password, self.credentials["password"])
        self.assertEqual(user.profile.role, UserProfile.Role.VIEWER)
        self.assertEqual(response.data["role"], UserProfile.Role.VIEWER)
        self.assertNotIn("password", response.data)

    def test_registration_accepts_username_without_email(self) -> None:
        """A username should be sufficient when the user chooses that mode."""
        payload = {
            "account": "username-only",
            "password": self.credentials["password"],
            "password_confirm": self.credentials["password_confirm"],
        }

        response = self.client.post(self.register_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = get_user_model().objects.get(username="username-only")
        self.assertEqual(user.email, "")

    def test_registration_and_login_accept_email_as_the_account(self) -> None:
        """An email-only account should register and authenticate directly."""
        payload = {
            "account": "Email.User@Example.com",
            "password": self.credentials["password"],
            "password_confirm": self.credentials["password_confirm"],
        }

        register_response = self.client.post(self.register_url, payload, format="json")
        login_response = self.client.post(
            self.login_url,
            {"account": "email.user@example.com", "password": payload["password"]},
            format="json",
        )

        self.assertEqual(register_response.status_code, status.HTTP_201_CREATED)
        user = get_user_model().objects.get(email="email.user@example.com")
        self.assertEqual(user.username, "email.user@example.com")
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        self.assertIn("access", login_response.data)

    def test_login_accepts_email_for_a_legacy_username_account(self) -> None:
        """Existing users should be able to authenticate with their stored email."""
        get_user_model().objects.create_user(
            username="legacy-user",
            email="legacy@example.com",
            password=self.credentials["password"],
        )

        response = self.client.post(
            self.login_url,
            {"account": "LEGACY@example.com", "password": self.credentials["password"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_registration_rejects_duplicate_single_account(self) -> None:
        """Account uniqueness should be enforced case-insensitively."""
        get_user_model().objects.create_user(username="taken-account")
        payload = {
            "account": "TAKEN-ACCOUNT",
            "password": self.credentials["password"],
            "password_confirm": self.credentials["password_confirm"],
        }

        response = self.client.post(self.register_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("account", response.data)

    def test_login_then_get_current_user_then_refresh_token(self) -> None:
        """A registered user should complete the contracted JWT flow."""
        self.client.post(self.register_url, self.credentials, format="json")
        login_response = self.client.post(
            self.login_url,
            {
                "username": self.credentials["username"],
                "password": self.credentials["password"],
            },
            format="json",
        )

        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        self.assertIn("access", login_response.data)
        self.assertIn("refresh", login_response.data)
        logged_in_user = get_user_model().objects.get(
            username=self.credentials["username"]
        )
        self.assertIsNotNone(logged_in_user.last_login)

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login_response.data['access']}"
        )
        me_response = self.client.get(self.me_url)
        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(me_response.data["username"], self.credentials["username"])

        refresh_response = self.client.post(
            self.refresh_url,
            {"refresh": login_response.data["refresh"]},
            format="json",
        )
        self.assertEqual(refresh_response.status_code, status.HTTP_200_OK)
        self.assertIn("access", refresh_response.data)

    def test_current_user_rejects_missing_or_invalid_token(self) -> None:
        """The current-user endpoint must not disclose data anonymously."""
        anonymous_response = self.client.get(self.me_url)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid-token")
        invalid_response = self.client.get(self.me_url)

        self.assertEqual(anonymous_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(invalid_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_registration_rejects_password_mismatch_without_creating_user(self) -> None:
        """A mismatched confirmation must fail atomically."""
        payload = {**self.credentials, "password_confirm": "Different-Password-2026!"}

        response = self.client.post(self.register_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(
            get_user_model().objects.filter(username=self.credentials["username"]).exists()
        )

    def test_registration_rejects_duplicate_email_case_insensitively(self) -> None:
        """Email identity must not be duplicated using different casing."""
        get_user_model().objects.create_user(
            username="existing-user",
            email="Tester@Example.com",
            password="Strong-Test-Password-2026!",
        )

        response = self.client.post(self.register_url, self.credentials, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)

    def test_login_rejects_wrong_password(self) -> None:
        """JWT tokens must not be issued for invalid credentials."""
        self.client.post(self.register_url, self.credentials, format="json")

        response = self.client.post(
            self.login_url,
            {"username": self.credentials["username"], "password": "wrong-password"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotIn("access", response.data)
