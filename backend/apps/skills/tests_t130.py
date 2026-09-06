"""Focused tests for T130 Skill permission isolation."""
from django.contrib.auth import get_user_model
from django.test import TestCase

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

