"""Focused REST and contract tests for the T167 Skill-chain foundation."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APITestCase

from apps.projects.models import Project, ProjectMember
from apps.skills.models import Skill, SkillChain, SkillChainConfiguration
from apps.users.models import UserProfile


class SkillChainContractTests(TestCase):
    """Cover canonical node, dependency and compatibility validation."""

    def setUp(self) -> None:
        """Create a Skill referenced by the contract fixtures."""
        self.skill = Skill.objects.create(name="T167 skill", category=Skill.Category.CORE)

    def definition(self) -> dict:
        """Return a complete two-node chain definition."""
        return {
            "nodes": [
                {
                    "node_id": "analyze",
                    "node_type": "skill",
                    "role": "core",
                    "skill_id": str(self.skill.id),
                    "skill_version_range": "*",
                    "execution_mode": "sequential",
                    "input_schema": {"type": "object"},
                    "output_schema": {"type": "object"},
                    "human_gate": "required",
                    "failure_strategy": "retry",
                    "depends_on": [],
                    "timeout_seconds": 60,
                    "max_retries": 2,
                },
                {
                    "node_id": "review",
                    "node_type": "human_gate",
                    "role": "related",
                    "execution_mode": "sequential",
                    "input_schema": {"type": "object"},
                    "output_schema": {"type": "object"},
                    "human_gate": "required",
                    "failure_strategy": "stop",
                    "depends_on": ["analyze"],
                },
            ],
            "merge_strategy": "required_only",
            "max_calls": 10,
            "max_runtime_seconds": 120,
            "max_cost_units": 0,
            "allowed_data_scopes": ["project.requirement"],
        }

    def test_model_normalizes_definition_and_rejects_legacy_only_shape(self) -> None:
        """A persisted chain contains explicit nodes rather than only Skill IDs."""
        chain = SkillChain.objects.create(name="T167 chain", definition=self.definition())
        chain.full_clean()
        self.assertEqual(chain.definition["schema_version"], "skill-chain-v1")
        self.assertEqual(chain.definition["nodes"][1]["depends_on"], ["analyze"])
        invalid = SkillChain(name="legacy", definition={"skill_ids": [str(self.skill.id)]})
        with self.assertRaises(ValidationError):
            invalid.full_clean()

    def test_cycle_and_non_unique_core_nodes_are_rejected(self) -> None:
        """Keep every persisted chain executable and bound to one core Skill."""
        cyclic = self.definition()
        cyclic["nodes"][0]["depends_on"] = ["review"]
        with self.assertRaises(ValidationError):
            SkillChain(name="cyclic", definition=cyclic).full_clean()

        no_core = self.definition()
        no_core["nodes"][0]["role"] = "related"
        with self.assertRaises(ValidationError):
            SkillChain(name="no-core", definition=no_core).full_clean()

        two_cores = self.definition()
        second_core = {**two_cores["nodes"][0], "node_id": "analyze-again"}
        two_cores["nodes"].append(second_core)
        with self.assertRaises(ValidationError):
            SkillChain(name="two-cores", definition=two_cores).full_clean()

    def test_non_skill_nodes_cannot_claim_skill_ids_or_core_role(self) -> None:
        """Keep human-gate and merge nodes distinct from actual Skill nodes."""
        invalid = self.definition()
        invalid["nodes"][1]["skill_id"] = str(self.skill.id)
        with self.assertRaises(ValidationError):
            SkillChain(name="human-skill-id", definition=invalid).full_clean()

        invalid = self.definition()
        invalid["nodes"][1]["role"] = "core"
        with self.assertRaises(ValidationError):
            SkillChain(name="human-core", definition=invalid).full_clean()


class SkillChainApiTests(APITestCase):
    """Cover authenticated REST access, scopes, configurations and errors."""

    def setUp(self) -> None:
        """Create administrator, project manager and an isolated project."""
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(username="t167-admin", password="Admin123456!")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save(update_fields=("role",))
        self.manager = user_model.objects.create_user(username="t167-manager", password="Manager123456!")
        self.project = Project.objects.create(name="T167 project", created_by=self.admin)
        ProjectMember.objects.create(project=self.project, user=self.manager, role=ProjectMember.Role.MANAGER)
        self.skill = Skill.objects.create(name="T167 API skill", category=Skill.Category.CORE)
        self.definition = {
            "nodes": [
                {
                    "node_id": "one",
                    "node_type": "skill",
                    "role": "core",
                    "skill_id": str(self.skill.id),
                    "input_schema": {},
                    "output_schema": {},
                    "depends_on": [],
                }
            ]
        }

    def test_admin_can_create_full_chain_and_four_layer_configuration(self) -> None:
        """Persist a complete chain and each layer's scope shape."""
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            "/api/skill-chains/",
            {"name": "T167 API chain", "version": "1.0.0", "definition": self.definition},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        chain_id = response.data["id"]
        self.assertEqual(response.data["definition"]["schema_version"], "skill-chain-v1")
        self.assertEqual(self.client.get("/api/skill-chains/").status_code, 200)
        global_configuration = None
        for payload in (
            {"chain": chain_id, "layer": "global"},
            {"chain": chain_id, "layer": "project", "project": str(self.project.id)},
            {"chain": chain_id, "layer": "feature", "project": str(self.project.id), "feature_key": "requirement_analysis"},
            {"chain": chain_id, "layer": "instant", "request_key": "t167-request"},
        ):
            created = self.client.post("/api/skill-chain-configurations/", payload, format="json")
            self.assertEqual(created.status_code, 201, created.data)
            snapshot = created.data["configuration_snapshot"]
            self.assertEqual(snapshot["snapshot_schema_version"], "skill-chain-configuration-v1")
            self.assertEqual(snapshot["layer"], payload["layer"])
            self.assertEqual(snapshot["chain"]["version"], "1.0.0")
            if payload["layer"] == "global":
                global_configuration = created.data
        self.assertEqual(SkillChainConfiguration.objects.filter(chain_id=chain_id).count(), 4)
        SkillChain.objects.filter(pk=chain_id).update(version="2.0.0")
        stored = self.client.get(
            f"/api/skill-chain-configurations/{global_configuration['id']}/"
        )
        self.assertEqual(stored.status_code, 200)
        self.assertEqual(stored.data["configuration_snapshot"]["chain"]["version"], "1.0.0")
        refreshed = self.client.patch(
            f"/api/skill-chain-configurations/{global_configuration['id']}/",
            {"overrides": {"max_calls": 12}},
            format="json",
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.data)
        self.assertEqual(refreshed.data["configuration_snapshot"]["chain"]["version"], "2.0.0")
        self.assertEqual(refreshed.data["configuration_snapshot"]["overrides"], {"max_calls": 12})

    def test_project_manager_cannot_bind_another_projects_chain(self) -> None:
        """Reject cross-project references even when the caller owns the target scope."""
        scoped_chain = SkillChain.objects.create(
            name="private-chain",
            project=self.project,
            definition=self.definition,
        )
        other_project = Project.objects.create(name="T167 other project", created_by=self.admin)
        other_manager = get_user_model().objects.create_user(username="t167-other-manager", password="Manager123456!")
        ProjectMember.objects.create(
            project=other_project,
            user=other_manager,
            role=ProjectMember.Role.MANAGER,
        )
        self.client.force_authenticate(other_manager)
        response = self.client.post(
            "/api/skill-chain-configurations/",
            {
                "chain": str(scoped_chain.id),
                "layer": "project",
                "project": str(other_project.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(SkillChainConfiguration.objects.filter(chain=scoped_chain).exists())

    def test_legacy_skill_id_list_and_unknown_dependency_are_rejected(self) -> None:
        """Do not let callers bypass the executable contract."""
        self.client.force_authenticate(self.admin)
        legacy = self.client.post(
            "/api/skill-chains/",
            {"name": "legacy-only", "definition": {"skill_ids": [str(self.skill.id)]}},
            format="json",
        )
        self.assertEqual(legacy.status_code, 400)
        invalid = {"nodes": [{**self.definition["nodes"][0], "depends_on": ["missing"]}]}
        response = self.client.post(
            "/api/skill-chains/",
            {"name": "unknown-dependency", "definition": invalid},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_project_manager_can_create_project_chain_but_anonymous_cannot(self) -> None:
        """Keep project scope writable by managers and closed to anonymous callers."""
        self.client.force_authenticate(self.manager)
        manager_response = self.client.post(
            "/api/skill-chains/",
            {"name": "project-chain", "project": str(self.project.id), "definition": self.definition},
            format="json",
        )
        self.assertEqual(manager_response.status_code, 201)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/skill-chains/").status_code, 401)
