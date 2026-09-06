"""Focused API tests for the third-party Skill management workbench."""
import base64

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.skills.models import SkillInstallation
from apps.skills.sources import PERMISSION_KEYS
from apps.skills.installation import sha256_bytes
from apps.users.models import UserProfile


class SkillInstallationApiTests(APITestCase):
    """Exercise the real administrator lifecycle endpoints end to end."""

    def setUp(self) -> None:
        self.admin = get_user_model().objects.create_user(username="installation-api-admin")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save(update_fields=("role",))
        self.viewer = get_user_model().objects.create_user(username="installation-api-viewer")
        self.artifact = b"t131 controlled artifact"
        permissions = {key: False for key in PERMISSION_KEYS}
        self.manifest = {
            "name": "api-skill",
            "version": "1.0.0",
            "author": "AITS",
            "license": "MIT",
            "file_hash": sha256_bytes(self.artifact),
            "permissions": permissions,
        }

    def test_admin_can_create_verify_approve_install_and_rollback(self) -> None:
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            "/api/skills/installations/",
            {"source_type": "local", "source_url": "local://skills/api-skill.zip", "manifest": self.manifest},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        installation_id = response.data["id"]
        self.assertEqual(response.data["status"], SkillInstallation.Status.PENDING)

        response = self.client.post(
            f"/api/skills/installations/{installation_id}/verify/",
            {"artifact_base64": base64.b64encode(self.artifact).decode(), "artifact_version": "1.0.0"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], SkillInstallation.Status.VERIFIED)
        self.assertEqual(self.client.post(f"/api/skills/installations/{installation_id}/approve/").status_code, 200)
        response = self.client.post(f"/api/skills/installations/{installation_id}/install/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], SkillInstallation.Status.INSTALLED)
        response = self.client.post(f"/api/skills/installations/{installation_id}/rollback/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], SkillInstallation.Status.ROLLED_BACK)

    def test_invalid_verification_is_recorded_as_failed(self) -> None:
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            "/api/skills/installations/",
            {"source_type": "local", "source_url": "local://skills/api-skill.zip", "manifest": self.manifest},
            format="json",
        )
        installation_id = response.data["id"]
        response = self.client.post(
            f"/api/skills/installations/{installation_id}/verify/",
            {"artifact_base64": base64.b64encode(b"wrong").decode()},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SkillInstallation.objects.get(pk=installation_id).status, SkillInstallation.Status.FAILED)

    def test_non_admin_cannot_manage_installations(self) -> None:
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get("/api/skills/installations/").status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/skills/installations/").status_code, 401)
