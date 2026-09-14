"""Focused API coverage for the T147 account onboarding and authorization flow."""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.models import AccountActionToken, AccountAuditEvent, UserProfile

User = get_user_model()


class AccountOnboardingApiTests(APITestCase):
    """Verify one-time invitations, reset links, revocation and permissions."""

    def setUp(self) -> None:
        """Create an administrator and a normal user for the permission matrix."""
        self.admin = User.objects.create_user(username="onboarding-admin", password="Admin-pass-123!")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save(update_fields=("role",))
        self.viewer = User.objects.create_user(username="onboarding-viewer", password="Viewer-pass-123!")

    @staticmethod
    def token_from(path: str) -> str:
        """Extract the opaque token from a returned frontend path."""
        return path.split("?token=", 1)[1]

    def test_admin_invites_and_colleague_activates_once(self) -> None:
        """An invitation creates an inactive account and cannot be replayed."""
        self.client.force_authenticate(self.admin)
        invited = self.client.post(
            "/api/auth/users/",
            {"account": "colleague", "role": UserProfile.Role.TESTER, "expires_in_hours": 24},
            format="json",
        )
        self.assertEqual(invited.status_code, status.HTTP_201_CREATED)
        self.assertIn("/activate?token=", invited.data["activation_path"])
        colleague = User.objects.get(username="colleague")
        self.assertFalse(colleague.is_active)
        self.assertTrue(invited.data["user"]["pending_invitation"])

        self.client.force_authenticate(None)
        token = self.token_from(invited.data["activation_path"])
        activated = self.client.post(
            "/api/auth/activate/",
            {"token": token, "password": "Colleague-pass-123!", "password_confirm": "Colleague-pass-123!"},
            format="json",
        )
        self.assertEqual(activated.status_code, status.HTTP_200_OK)
        colleague.refresh_from_db()
        self.assertTrue(colleague.is_active)
        self.assertTrue(
            AccountAuditEvent.objects.filter(
                event=AccountAuditEvent.Event.INVITED,
                target_username="colleague",
            ).exists()
        )
        self.assertTrue(
            AccountAuditEvent.objects.filter(
                event=AccountAuditEvent.Event.ACTIVATED,
                target_username="colleague",
            ).exists()
        )
        replay = self.client.post(
            "/api/auth/activate/",
            {"token": token, "password": "Another-pass-123!", "password_confirm": "Another-pass-123!"},
            format="json",
        )
        self.assertEqual(replay.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_invite_requires_resend_and_revoke_blocks_link(self) -> None:
        """Repeated onboarding is explicit and revoked links cannot activate an account."""
        self.client.force_authenticate(self.admin)
        first = self.client.post("/api/auth/users/", {"account": "pending-user"}, format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        duplicate = self.client.post("/api/auth/users/", {"account": "pending-user"}, format="json")
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)
        user = User.objects.get(username="pending-user")
        resent = self.client.post(f"/api/auth/users/{user.pk}/resend-invitation/")
        self.assertEqual(resent.status_code, status.HTTP_200_OK)
        self.assertEqual(
            AccountActionToken.objects.filter(user=user, kind=AccountActionToken.Kind.INVITATION, used_at__isnull=True).count(),
            1,
        )
        revoked = self.client.post(f"/api/auth/users/{user.pk}/revoke-actions/")
        self.assertEqual(revoked.status_code, status.HTTP_200_OK)
        self.client.force_authenticate(None)
        activation = self.client.post(
            "/api/auth/activate/",
            {"token": self.token_from(resent.data["activation_path"]), "password": "Pending-pass-123!", "password_confirm": "Pending-pass-123!"},
            format="json",
        )
        self.assertEqual(activation.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_resets_active_user_password_once(self) -> None:
        """Administrator reset links change passwords and are single-use."""
        self.client.force_authenticate(self.admin)
        link = self.client.post(f"/api/auth/users/{self.viewer.pk}/password-reset-link/")
        self.assertEqual(link.status_code, status.HTTP_200_OK)
        self.client.force_authenticate(None)
        token = self.token_from(link.data["reset_path"])
        reset = self.client.post(
            "/api/auth/password-reset/",
            {"token": token, "password": "Reset-pass-123!", "password_confirm": "Reset-pass-123!"},
            format="json",
        )
        self.assertEqual(reset.status_code, status.HTTP_200_OK)
        login = self.client.post(
            "/api/auth/login/",
            {"account": "onboarding-viewer", "password": "Reset-pass-123!"},
            format="json",
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.client.force_authenticate(self.admin)
        audit = self.client.get("/api/auth/audit-events/")
        self.assertEqual(audit.status_code, status.HTTP_200_OK)
        self.assertTrue(any(item["event"] == AccountAuditEvent.Event.PASSWORD_RESET_ISSUED for item in audit.data))
        self.assertTrue(all("token" not in str(item).lower() for item in audit.data))

    def test_non_admin_cannot_issue_account_actions(self) -> None:
        """Account lifecycle controls remain administrator-only."""
        self.client.force_authenticate(self.viewer)
        self.assertEqual(
            self.client.post("/api/auth/users/", {"account": "blocked-user"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(f"/api/auth/users/{self.admin.pk}/password-reset-link/").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.get("/api/auth/audit-events/").status_code,
            status.HTTP_403_FORBIDDEN,
        )
