"""Focused API tests for uploaded third-party Skills folders."""

import base64
import hashlib

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.skills.models import SkillInstallation
from apps.skills.sources import PERMISSION_KEYS
from apps.users.models import UserProfile


class SkillFolderUploadApiTests(APITestCase):
    """Verify folder normalization, SKILL.md requirements and path safety."""

    def setUp(self) -> None:
        """Create an administrator and a deterministic folder artifact."""
        self.admin = get_user_model().objects.create_user(username="folder-admin")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save(update_fields=("role",))
        self.files = [
            {"path": "demo-skill/SKILL.md", "content": b"# Demo Skill\n"},
            {"path": "demo-skill/README.md", "content": b"safe documentation"},
        ]
        canonical = bytearray()
        for item in sorted(self.files, key=lambda value: value["path"]):
            path = item["path"].encode()
            content = item["content"]
            canonical.extend(path + b"\0" + str(len(content)).encode() + b"\0" + content)
        self.manifest = {
            "name": "demo-folder-skill",
            "version": "1.0.0",
            "author": "AITS",
            "license": "MIT",
            "file_hash": hashlib.sha256(bytes(canonical)).hexdigest(),
            "permissions": {key: False for key in PERMISSION_KEYS},
        }

    def create_installation(self) -> str:
        """Create one pending installation and return its identifier."""
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            "/api/skills/installations/",
            {
                "source_type": "local",
                "source_url": "local://demo-skill",
                "manifest": self.manifest,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        return response.data["id"]

    def artifact_payload(self, files=None) -> list[dict[str, str]]:
        """Encode folder files using the API's explicit path/content contract."""
        return [
            {"path": item["path"], "content_base64": base64.b64encode(item["content"]).decode()}
            for item in (files or self.files)
        ]

    def test_folder_with_skill_md_can_be_verified(self) -> None:
        """A selected folder reaches verified state without saving source files."""
        installation_id = self.create_installation()
        response = self.client.post(
            f"/api/skills/installations/{installation_id}/verify/",
            {"artifact_files": self.artifact_payload(), "artifact_version": "1.0.0"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], SkillInstallation.Status.VERIFIED)

    def test_folder_requires_skill_md_and_rejects_traversal(self) -> None:
        """Missing manifests and unsafe paths fail closed and remain auditable."""
        missing_manifest = [{"path": "demo-skill/README.md", "content": b"readme"}]
        installation_id = self.create_installation()
        response = self.client.post(
            f"/api/skills/installations/{installation_id}/verify/",
            {"artifact_files": self.artifact_payload(missing_manifest)},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SkillInstallation.objects.get(pk=installation_id).status, SkillInstallation.Status.FAILED)

        traversal_id = self.create_installation()
        response = self.client.post(
            f"/api/skills/installations/{traversal_id}/verify/",
            {"artifact_files": self.artifact_payload([{"path": "../SKILL.md", "content": b"bad"}])},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("unsafe path", response.data["detail"])
