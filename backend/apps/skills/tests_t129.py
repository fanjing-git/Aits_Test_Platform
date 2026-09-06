"""Focused tests for T129 installation verification and audit lifecycle."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.skills.installation import (
    SkillInstallationError,
    approve_installation,
    install_verified,
    request_installation,
    rollback_installation,
    sha256_bytes,
    uninstall_installation,
    verify_installation,
)
from apps.skills.models import SkillInstallation
from apps.skills.sources import PERMISSION_KEYS, discover_skill_manifest
from apps.users.models import UserProfile


class SkillInstallationTests(TestCase):
    """Verify hash gates, administrator approval and reversible lifecycle states."""

    def setUp(self) -> None:
        self.admin = get_user_model().objects.create_user(username="install-admin")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save(update_fields=("role",))
        self.viewer = get_user_model().objects.create_user(username="install-viewer")
        self.content = b"safe third-party package fixture"
        self.manifest = discover_skill_manifest(
            "local://skills/demo-1.0.0.zip",
            {
                "name": "remote-demo",
                "version": "1.0.0",
                "author": "AITS Team",
                "license": "MIT",
                "file_hash": sha256_bytes(self.content),
                "permissions": {key: False for key in PERMISSION_KEYS},
            },
            source="local",
        )

    def test_install_requires_hash_verification_and_admin_approval(self) -> None:
        installation = request_installation(self.manifest, requested_by=self.viewer)
        with self.assertRaisesRegex(SkillInstallationError, "verification"):
            install_verified(installation, self.admin)
        verify_installation(installation, self.content, artifact_version="1.0.0")
        with self.assertRaisesRegex(SkillInstallationError, "administrator"):
            approve_installation(installation, self.viewer)
        approve_installation(installation, self.admin)
        install_verified(installation, self.admin)
        installation.refresh_from_db()
        self.assertEqual(installation.status, SkillInstallation.Status.INSTALLED)
        self.assertEqual(installation.installed_by_id, self.admin.id)

    def test_hash_or_version_mismatch_fails_and_is_recorded(self) -> None:
        installation = request_installation(self.manifest, requested_by=self.viewer)
        with self.assertRaisesRegex(SkillInstallationError, "hash"):
            verify_installation(installation, b"tampered", artifact_version="1.0.0")
        installation.refresh_from_db()
        self.assertEqual(installation.status, SkillInstallation.Status.FAILED)
        self.assertIn("hash", installation.error_message)
        installation = request_installation(self.manifest, requested_by=self.viewer)
        with self.assertRaisesRegex(SkillInstallationError, "version"):
            verify_installation(installation, self.content, artifact_version="9.9.9")

    def test_rollback_and_uninstall_retain_audit_record(self) -> None:
        installation = request_installation(self.manifest, requested_by=self.viewer)
        verify_installation(installation, self.content)
        approve_installation(installation, self.admin)
        install_verified(installation, self.admin)
        rollback_installation(installation, self.admin)
        installation.refresh_from_db()
        self.assertEqual(installation.status, SkillInstallation.Status.ROLLED_BACK)
        self.assertIsNotNone(installation.rolled_back_at)

        installation = request_installation(self.manifest, requested_by=self.viewer)
        verify_installation(installation, self.content)
        approve_installation(installation, self.admin)
        install_verified(installation, self.admin)
        uninstall_installation(installation, self.admin)
        installation.refresh_from_db()
        self.assertEqual(installation.status, SkillInstallation.Status.UNINSTALLED)
        self.assertIsNotNone(installation.created_at)
