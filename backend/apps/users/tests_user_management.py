"""API tests for the user and role management remediation."""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.models import UserProfile

User = get_user_model()


class UserManagementApiTests(APITestCase):
    def setUp(self) -> None:
        self.admin = User.objects.create_user(username="admin", password="password")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save(update_fields=("role",))
        self.viewer = User.objects.create_user(username="viewer", password="password")

    def test_admin_can_list_users_without_sensitive_fields(self) -> None:
        self.client.force_authenticate(self.admin)

        response = self.client.get("/api/auth/users/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["username"] for item in response.data], ["admin", "viewer"])
        self.assertNotIn("password", response.data[0])

    def test_admin_can_assign_role_and_change_active_state(self) -> None:
        self.client.force_authenticate(self.admin)

        response = self.client.patch(
            f"/api/auth/users/{self.viewer.pk}/",
            {"role": UserProfile.Role.TESTER, "is_active": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.viewer.refresh_from_db()
        self.viewer.profile.refresh_from_db()
        self.assertEqual(self.viewer.profile.role, UserProfile.Role.TESTER)
        self.assertFalse(self.viewer.is_active)

    def test_non_admin_and_anonymous_users_are_denied(self) -> None:
        self.client.force_authenticate(self.viewer)
        self.assertEqual(
            self.client.get("/api/auth/users/").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.get("/api/auth/users/").status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_last_admin_cannot_demote_or_deactivate_self(self) -> None:
        self.client.force_authenticate(self.admin)

        demote = self.client.patch(
            f"/api/auth/users/{self.admin.pk}/",
            {"role": UserProfile.Role.VIEWER},
            format="json",
        )
        deactivate = self.client.patch(
            f"/api/auth/users/{self.admin.pk}/",
            {"is_active": False},
            format="json",
        )

        self.assertEqual(demote.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(deactivate.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_can_change_own_role_when_another_active_admin_exists(self) -> None:
        replacement = User.objects.create_user(username="replacement-admin")
        replacement.profile.role = UserProfile.Role.ADMIN
        replacement.profile.save(update_fields=("role",))
        self.client.force_authenticate(self.admin)

        response = self.client.patch(
            f"/api/auth/users/{self.admin.pk}/",
            {"role": UserProfile.Role.TEST_LEADER},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.admin.profile.refresh_from_db()
        self.assertEqual(self.admin.profile.role, UserProfile.Role.TEST_LEADER)
