"""Focused tests for T168 Skill-chain resolution and governance."""

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.projects.models import Project, ProjectMember
from apps.skills.models import (
    Skill,
    SkillChain,
    SkillChainConfiguration,
    SkillChainGovernanceAudit,
    SkillInstallation,
)
from apps.skills.services import resolve_skill_chain_configuration
from apps.users.models import UserProfile


class SkillChainTestData:
    """Share isolated fixture builders without inheriting test methods."""

    def setUp(self) -> None:
        """Create visible project roles and one enabled capability."""
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(username="t168-admin", password="Admin123456!")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save(update_fields=("role",))
        self.manager = user_model.objects.create_user(username="t168-manager", password="Manager123456!")
        self.outsider = user_model.objects.create_user(username="t168-outsider", password="Manager123456!")
        self.viewer = user_model.objects.create_user(username="t168-viewer", password="Viewer123456!")
        self.project = Project.objects.create(name="T168 project", created_by=self.admin)
        ProjectMember.objects.create(project=self.project, user=self.manager, role=ProjectMember.Role.MANAGER)
        ProjectMember.objects.create(project=self.project, user=self.viewer, role=ProjectMember.Role.VIEWER)
        self.skill = Skill.objects.create(name="T168 analysis", version="1.2.0", category=Skill.Category.CORE)
        self.definition = {
            "nodes": [{
                "node_id": "analysis",
                "node_type": "skill",
                "role": "core",
                "skill_id": str(self.skill.pk),
                "skill_version_range": "*",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "depends_on": [],
            }],
            "max_calls": 20,
            "max_runtime_seconds": 300,
            "allowed_data_scopes": ["project.requirement"],
        }

    def make_chain(self, name: str, *, project=None, version: str = "1.0.0", status: str = SkillChain.Status.ENABLED):
        """Create one valid chain fixture in the requested scope."""
        return SkillChain.objects.create(
            name=name,
            project=project,
            version=version,
            status=status,
            published_at=timezone.now() if status in {
                SkillChain.Status.PUBLISHED,
                SkillChain.Status.ENABLED,
                SkillChain.Status.PAUSED,
                SkillChain.Status.DISABLED,
                SkillChain.Status.ARCHIVED,
            } else None,
            definition=self.definition,
            created_by=self.admin,
        )

    def make_config(self, chain, layer: str, **kwargs):
        """Create a persisted layer configuration with a snapshot."""
        return SkillChainConfiguration.objects.create(
            chain=chain,
            layer=layer,
            created_by=self.admin,
            **kwargs,
        )

    def test_precedence_and_recursive_field_merge(self) -> None:
        """Higher layers win on overlapping keys and inherit lower-layer fields."""
        global_chain = self.make_chain("Global")
        project_chain = self.make_chain("Project", project=self.project)
        feature_chain = self.make_chain("Feature")
        self.make_config(global_chain, "global", overrides={"max_calls": 50})
        self.make_config(project_chain, "project", project=self.project, overrides={"max_runtime_seconds": 120})
        self.make_config(
            feature_chain,
            "feature",
            project=self.project,
            feature_key="requirement_analysis",
            version_lock="1.0.0",
            overrides={"max_calls": 8},
        )

        result = resolve_skill_chain_configuration(
            project_id=self.project.pk,
            feature_key="requirement_analysis",
        )

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["source_layer"], "feature")
        self.assertEqual(result["chain"]["name"], "Feature")
        self.assertEqual(result["definition"]["max_calls"], 8)
        self.assertEqual(result["definition"]["max_runtime_seconds"], 120)
        self.assertEqual([item["layer"] for item in result["layers"]], ["global", "project", "feature"])
        self.assertFalse(result["runtime_ready"])

    def test_conflict_disabled_and_version_lock_are_explicit_blockers(self) -> None:
        """Never fall through when same-layer configuration or safety checks fail."""
        first = self.make_chain("Global A")
        second = self.make_chain("Global B")
        self.make_config(first, "global")
        self.make_config(second, "global")
        conflict = resolve_skill_chain_configuration()
        self.assertEqual(conflict["reason_code"], "configuration_conflict")

        SkillChainConfiguration.objects.all().delete()
        self.make_config(first, "global")
        self.make_config(
            self.make_chain("Project override", project=self.project),
            "project",
            project=self.project,
            enabled=False,
        )
        disabled = resolve_skill_chain_configuration(project_id=self.project.pk)
        self.assertEqual(disabled["reason_code"], "configuration_disabled")

        SkillChainConfiguration.objects.all().delete()
        self.make_config(first, "global", version_lock="9.9.9")
        locked = resolve_skill_chain_configuration()
        self.assertEqual(locked["reason_code"], "version_lock_mismatch")

    def test_disabled_skill_and_incompatible_skill_version_block_resolution(self) -> None:
        """A missing or incompatible capability blocks the selected chain."""
        self.definition["nodes"][0]["skill_version_range"] = ">=2.0.0"
        chain = self.make_chain("Capability guarded")
        self.make_config(chain, "global")
        self.skill.status = Skill.Status.DISABLED
        self.skill.save(update_fields=("status", "updated_at"))
        disabled = resolve_skill_chain_configuration()
        self.assertEqual(disabled["reason_code"], "skill_not_compatible")
        self.skill.status = Skill.Status.ENABLED
        self.skill.save(update_fields=("status", "updated_at"))
        incompatible = resolve_skill_chain_configuration()
        self.assertEqual(incompatible["reason_code"], "skill_not_compatible")
        self.assertEqual(incompatible["issues"][0]["code"], "skill_version_incompatible")

    def test_immediate_selection_overrides_scope_by_name_reference(self) -> None:
        """An immediate chain choice becomes the highest preview layer."""
        global_chain = self.make_chain("Global default")
        instant_chain = self.make_chain("Chosen now")
        self.make_config(global_chain, "global")
        result = resolve_skill_chain_configuration(
            project_id=self.project.pk,
            feature_key="requirement_analysis",
            instant_chain_id=str(instant_chain.pk),
        )
        self.assertEqual(result["source_layer"], "instant")
        self.assertEqual(result["chain"]["name"], "Chosen now")


class SkillChainResolutionTests(SkillChainTestData, APITestCase):
    """Verify REST permissions, lifecycle, audit history and rollback."""

    def test_configuration_crud_is_scoped_and_rollback_is_audited(self) -> None:
        """Project managers may configure their project and restore prior state."""
        chain = self.make_chain("Governed", project=self.project)
        self.client.force_authenticate(self.manager)
        created = self.client.post(
            "/api/skill-chain-configurations/",
            {"chain": str(chain.pk), "layer": "project", "project": str(self.project.pk), "version_lock": "1.0.0"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertFalse(created.data["can_rollback"])
        first_rollback = self.client.post(
            f"/api/skill-chain-configurations/{created.data['id']}/rollback/", {}, format="json"
        )
        self.assertEqual(first_rollback.status_code, 409)
        self.assertEqual(first_rollback.data["reason_code"], "no_rollback_target")
        configuration_id = created.data["id"]
        changed = self.client.patch(
            f"/api/skill-chain-configurations/{configuration_id}/",
            {"overrides": {"max_calls": 7}},
            format="json",
        )
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertTrue(changed.data["can_rollback"])
        restored = self.client.post(f"/api/skill-chain-configurations/{configuration_id}/rollback/", {}, format="json")
        self.assertEqual(restored.status_code, 200, restored.data)
        self.assertEqual(restored.data["overrides"], {})
        history = self.client.get(f"/api/skill-chain-configurations/{configuration_id}/history/")
        self.assertEqual(history.status_code, 200)
        self.assertEqual([item["action"] for item in history.data], ["rollback", "update", "create"])
        self.assertEqual(history.data[0]["actor_display_name"], self.manager.get_username())
        self.assertEqual(history.data[0]["actor_scope"]["project_role"], ProjectMember.Role.MANAGER)
        self.assertNotIn("definition", history.data[0]["after_state"]["configuration_snapshot"]["chain"])
        self.client.force_authenticate(self.viewer)
        audit_denied = self.client.get(f"/api/skill-chain-configurations/{configuration_id}/history/")
        self.assertEqual(audit_denied.status_code, 403)

    def test_create_permission_and_anonymous_resolution(self) -> None:
        """Unauthorized project/global writes fail with 403 and anonymous preview with 401."""
        chain = self.make_chain("Restricted", project=self.project)
        self.client.force_authenticate(self.outsider)
        denied = self.client.post(
            "/api/skill-chain-configurations/",
            {"chain": str(chain.pk), "layer": "project", "project": str(self.project.pk)},
            format="json",
        )
        self.assertEqual(denied.status_code, 403)
        self.client.force_authenticate(self.manager)
        global_denied = self.client.post(
            "/api/skill-chain-configurations/",
            {"chain": str(self.make_chain("Global").pk), "layer": "global"},
            format="json",
        )
        self.assertEqual(global_denied.status_code, 403)
        self.client.force_authenticate(None)
        preview = self.client.post("/api/skill-chain-configurations/resolve/", {}, format="json")
        self.assertEqual(preview.status_code, 401)

    def test_blueprint_lifecycle_audit_first_version_and_permissions(self) -> None:
        """A first blueprint has no rollback target, and actors/scope are captured server-side."""
        self.client.force_authenticate(self.manager)
        created = self.client.post(
            "/api/skill-chains/",
            {
                "project": str(self.project.pk),
                "name": "Lifecycle",
                "version": "1.0.0",
                "description": "T168 lifecycle fixture",
                "definition": self.definition,
                "actor": "spoofed",
                "created_by": str(self.outsider.pk),
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        chain_id = created.data["id"]
        published_definition = created.data["definition"]
        self.assertEqual(created.data["status"], SkillChain.Status.DRAFT)
        self.assertFalse(created.data["can_rollback"])
        audits = SkillChainGovernanceAudit.objects.filter(chain_id=chain_id)
        self.assertEqual(audits.count(), 1)
        self.assertEqual(audits.get().action, "chain_create")
        self.assertEqual(audits.get().actor_id, self.manager.pk)
        self.assertEqual(audits.get().actor_display_name, self.manager.get_username())
        self.assertEqual(audits.get().actor_scope["project_id"], str(self.project.pk))

        first_rollback = self.client.post(f"/api/skill-chains/{chain_id}/rollback/", {}, format="json")
        self.assertEqual(first_rollback.status_code, 409)
        self.assertEqual(first_rollback.data["reason_code"], "no_rollback_target")
        self.assertEqual(SkillChainGovernanceAudit.objects.filter(chain_id=chain_id).count(), 1)

        verified = self.client.post(f"/api/skill-chains/{chain_id}/verify/", {}, format="json")
        self.assertEqual(verified.status_code, 200, verified.data)
        self.assertEqual(verified.data["status"], SkillChain.Status.VERIFIED)
        published = self.client.post(f"/api/skill-chains/{chain_id}/publish/", {}, format="json")
        self.assertEqual(published.status_code, 200, published.data)
        self.assertIsNotNone(published.data["published_at"])
        enabled = self.client.post(f"/api/skill-chains/{chain_id}/enable/", {}, format="json")
        self.assertEqual(enabled.status_code, 200, enabled.data)
        self.assertEqual(enabled.data["status"], SkillChain.Status.ENABLED)

        forked = self.client.post(f"/api/skill-chains/{chain_id}/fork/", {}, format="json")
        self.assertEqual(forked.status_code, 201, forked.data)
        draft_id = forked.data["id"]
        self.assertEqual(forked.data["version"], "1.0.1")
        self.assertEqual(forked.data["status"], SkillChain.Status.DRAFT)
        self.assertEqual(forked.data["definition"], published_definition)
        changed_definition = dict(published_definition)
        changed_definition["max_calls"] = 37
        updated = self.client.patch(
            f"/api/skill-chains/{draft_id}/",
            {"definition": changed_definition},
            format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["definition"]["max_calls"], 37)
        second_verified = self.client.post(f"/api/skill-chains/{draft_id}/verify/", {}, format="json")
        self.assertEqual(second_verified.status_code, 200, second_verified.data)
        second_published = self.client.post(f"/api/skill-chains/{draft_id}/publish/", {}, format="json")
        self.assertEqual(second_published.status_code, 200, second_published.data)
        second_enabled = self.client.post(f"/api/skill-chains/{draft_id}/enable/", {}, format="json")
        self.assertEqual(second_enabled.status_code, 200, second_enabled.data)
        self.assertEqual(second_enabled.data["status"], SkillChain.Status.ENABLED)
        self.assertEqual(
            SkillChain.objects.get(pk=chain_id).status,
            SkillChain.Status.PUBLISHED,
            "Enabling v2 must retire v1 from new-run selection.",
        )

        versions = self.client.get(f"/api/skill-chains/{draft_id}/versions/")
        self.assertEqual(versions.status_code, 200)
        self.assertEqual({item["version"] for item in versions.data}, {"1.0.0", "1.0.1"})
        diff = self.client.get(f"/api/skill-chains/{draft_id}/diff/?compare_to={chain_id}")
        self.assertEqual(diff.status_code, 200, diff.data)
        self.assertEqual(diff.data["definition_fields_changed"], ["max_calls"])
        self.assertNotIn("definition", diff.data)

        rollback = self.client.post(
            f"/api/skill-chains/{draft_id}/rollback/",
            {"target_version_id": chain_id},
            format="json",
        )
        self.assertEqual(rollback.status_code, 201, rollback.data)
        self.assertEqual(rollback.data["version"], "1.0.2")
        self.assertEqual(rollback.data["status"], SkillChain.Status.DRAFT)
        self.assertEqual(rollback.data["definition"], published_definition)
        self.assertEqual(SkillChain.objects.get(pk=draft_id).status, SkillChain.Status.ENABLED)

        self.client.force_authenticate(self.viewer)
        versions_read = self.client.get(f"/api/skill-chains/{draft_id}/versions/")
        self.assertEqual(versions_read.status_code, 200)
        history_denied = self.client.get(f"/api/skill-chains/{draft_id}/history/")
        self.assertEqual(history_denied.status_code, 403)
        self.client.force_authenticate(None)
        anonymous_history = self.client.get(f"/api/skill-chains/{draft_id}/history/")
        self.assertEqual(anonymous_history.status_code, 401)

    def test_chain_enable_disable_and_install_readiness_are_separate(self) -> None:
        """Legacy disable remains a pause alias, and install does not fabricate readiness."""
        chain = self.make_chain("Lifecycle", status=SkillChain.Status.PUBLISHED)
        self.client.force_authenticate(self.admin)
        enabled = self.client.post(f"/api/skill-chains/{chain.pk}/enable/", {}, format="json")
        self.assertEqual(enabled.status_code, 200, enabled.data)
        disabled = self.client.post(f"/api/skill-chains/{chain.pk}/disable/", {}, format="json")
        self.assertEqual(disabled.status_code, 200, disabled.data)
        self.assertEqual(disabled.data["status"], SkillChain.Status.PAUSED)
        self.assertEqual(
            SkillChainGovernanceAudit.objects.filter(chain=chain).values_list("action", flat=True).order_by("created_at").last(),
            "chain_pause",
        )
        installation = SkillInstallation.objects.create(
            skill=self.skill,
            source_type="local",
            source_url="local://t168-fixture",
            version="1.2.0",
            status=SkillInstallation.Status.INSTALLED,
        )
        response = self.client.get("/api/skills/installations/")
        self.assertEqual(response.status_code, 200)
        row = next(item for item in response.data if item["id"] == str(installation.pk))
        self.assertEqual(row["linked_skill_name"], self.skill.name)
        self.assertTrue(row["installed"])
        self.assertFalse(row["runtime_ready"])
        self.assertIn("安装成功不代表", row["runtime_ready_reason"])
