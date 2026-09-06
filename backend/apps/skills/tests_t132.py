"""Focused end-to-end tests for the third-party Skill safety boundary."""
import base64

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.skills.installation import sha256_bytes
from apps.skills.models import Skill, SkillPermissionAudit
from apps.skills.sources import PERMISSION_KEYS
from apps.users.models import UserProfile


class SkillExtensionEndToEndTests(APITestCase):
    """Verify simulated source discovery and controlled invocation/revocation."""

    def setUp(self) -> None:
        self.admin = get_user_model().objects.create_user(username="t132-admin")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save(update_fields=("role",))
        self.artifact = b"t132 fixture"
        permissions = {key: False for key in PERMISSION_KEYS}
        permissions["network"] = True
        self.manifest = {
            "name": "t132-network-skill",
            "version": "1.0.0",
            "author": "AITS",
            "license": "MIT",
            "file_hash": sha256_bytes(self.artifact),
            "permissions": permissions,
        }

    def create_source(self, source_type: str, source_url: str) -> dict:
        response = self.client.post(
            "/api/skills/installations/",
            {"source_type": source_type, "source_url": source_url, "manifest": self.manifest},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        return response.data

    def test_local_github_and_skillhub_sources_are_discovered_without_network(self) -> None:
        self.client.force_authenticate(self.admin)
        self.create_source("local", "local://t132-network-skill.zip")
        self.create_source("github", "https://github.com/aits/t132-network-skill?ref=v1.0.0")
        self.create_source("skillhub", "https://skillhub.example/skills/t132-network-skill?version=1.0.0")
        self.assertEqual(self.client.get("/api/skills/installations/").status_code, 200)

    def test_install_invoke_and_revoke_are_connected_to_permission_guard(self) -> None:
        self.client.force_authenticate(self.admin)
        installation = self.create_source("local", "local://t132-network-skill.zip")
        installation_id = installation["id"]
        encoded = base64.b64encode(self.artifact).decode()
        self.assertEqual(self.client.post(f"/api/skills/installations/{installation_id}/verify/", {"artifact_base64": encoded}, format="json").status_code, 200)
        self.assertEqual(self.client.post(f"/api/skills/installations/{installation_id}/approve/").status_code, 200)
        installed = self.client.post(f"/api/skills/installations/{installation_id}/install/")
        self.assertEqual(installed.status_code, 200)
        self.assertIsNotNone(installed.data["skill"])
        invoked = self.client.post(f"/api/skills/installations/{installation_id}/invoke/", {"permission": "network", "input": {"message": "hello"}}, format="json")
        self.assertEqual(invoked.status_code, 200)
        self.assertEqual(invoked.data["result"]["echo"]["message"], "hello")
        self.assertEqual(SkillPermissionAudit.objects.filter(installation_id=installation_id, allowed=True).count(), 1)
        self.assertEqual(self.client.post(f"/api/skills/installations/{installation_id}/rollback/").status_code, 200)
        denied = self.client.post(f"/api/skills/installations/{installation_id}/invoke/", {"permission": "network", "input": {}}, format="json")
        self.assertEqual(denied.status_code, 400)
        self.assertEqual(SkillPermissionAudit.objects.filter(installation_id=installation_id, allowed=False).count(), 1)
        self.assertEqual(Skill.objects.get(pk=installed.data["skill"]).status, Skill.Status.DISABLED)
