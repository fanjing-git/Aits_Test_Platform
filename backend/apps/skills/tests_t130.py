"""Focused tests for T130 Skill permission isolation."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APITestCase

from apps.skills.installation import (
    approve_installation,
    install_verified,
    request_installation,
    sha256_bytes,
    verify_installation,
)
from apps.skills.models import SkillPermissionAudit
from apps.skills.permissions import SkillPermissionError, enforce_skill_permission
from apps.skills.sources import PERMISSION_KEYS, discover_skill_manifest
from apps.users.models import UserProfile


class SkillPermissionIsolationTests(TestCase):
    """Verify default deny, explicit grants and redacted permission auditing."""

    def setUp(self) -> None:
        self.admin = get_user_model().objects.create_user(username="permission-admin")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save(update_fields=("role",))
        self.content = b"permission fixture"
        permissions = {key: False for key in PERMISSION_KEYS}
        permissions["network"] = True
        manifest = discover_skill_manifest(
            "local://skills/permission-demo-1.0.0.zip",
            {
                "name": "permission-demo",
                "version": "1.0.0",
                "author": "AITS Team",
                "license": "MIT",
                "file_hash": sha256_bytes(self.content),
                "permissions": permissions,
            },
            source="local",
        )
        installation = request_installation(manifest, requested_by=self.admin)
        verify_installation(installation, self.content)
        approve_installation(installation, self.admin)
        self.installation = install_verified(installation, self.admin)

    def test_explicit_permission_is_allowed_and_audited(self) -> None:
        self.assertTrue(
            enforce_skill_permission(
                self.installation,
                "network",
                actor=self.admin,
                context={"url": "https://secret.example", "token": "redact-me"},
            )
        )
        audit = SkillPermissionAudit.objects.get(permission="network")
        self.assertTrue(audit.allowed)
        self.assertEqual(audit.context_keys, ["token", "url"])
        self.assertNotIn("secret", audit.reason)

    def test_unlisted_permission_is_denied_even_for_an_admin(self) -> None:
        with self.assertRaisesRegex(SkillPermissionError, "denied"):
            enforce_skill_permission(self.installation, "file", actor=self.admin)
        audit = SkillPermissionAudit.objects.get(permission="file")
        self.assertFalse(audit.allowed)

    def test_non_installed_skill_is_denied_by_default(self) -> None:
        self.installation.status = self.installation.Status.ROLLED_BACK
        self.installation.save(update_fields=("status",))
        with self.assertRaises(SkillPermissionError):
            enforce_skill_permission(self.installation, "network", actor=self.admin)

    def test_unknown_permission_fails_without_creating_an_audit_record(self) -> None:
        with self.assertRaisesRegex(SkillPermissionError, "unsupported"):
            enforce_skill_permission(self.installation, "shell", actor=self.admin)
        self.assertEqual(SkillPermissionAudit.objects.count(), 0)


class SkillPermissionAuditApiTests(APITestCase):
    """Verify the audit feed is reachable by administrators and protected for others."""

    def setUp(self) -> None:
        self.admin = get_user_model().objects.create_user(username="audit-api-admin")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save(update_fields=("role",))
        self.viewer = get_user_model().objects.create_user(username="audit-api-viewer")
        from apps.skills.models import SkillInstallation

        installation = SkillInstallation.objects.create(
            source_type="local",
            source_url="skills/demo",
            version="1.0.0",
            manifest={"permissions": {key: False for key in PERMISSION_KEYS}},
        )
        SkillPermissionAudit.objects.create(
            installation=installation,
            permission="network",
            allowed=False,
            reason="permission denied by installation policy",
            context_keys=["url"],
            actor=self.viewer,
        )

    def test_admin_can_read_safe_audit_feed(self) -> None:
        self.client.force_authenticate(self.admin)
        response = self.client.get("/api/skills/permission-audits/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["permission"], "network")
        self.assertEqual(response.data[0]["context_keys"], ["url"])

    def test_non_admin_is_forbidden_and_anonymous_is_unauthorized(self) -> None:
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get("/api/skills/permission-audits/").status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/skills/permission-audits/").status_code, 401)
