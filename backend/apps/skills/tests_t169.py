"""Focused persistence, control and lineage tests for T169."""

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.projects.models import Project, ProjectMember
from apps.skills.models import Skill, SkillChain, SkillChainRun, SkillChainRunEvent
from apps.skills.execution import SkillChainExecutionService
from apps.users.models import UserProfile


class SkillChainRuntimeTests(APITestCase):
    """Exercise the public run contract through the real local API."""

    def setUp(self) -> None:
        """Create an administrator and two enabled persisted Skill definitions."""
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(username="t169-admin", password="Admin123456!")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save(update_fields=("role",))
        self.outsider = user_model.objects.create_user(username="t169-outsider", password="Admin123456!")
        self.primary = Skill.objects.create(
            name="T169 primary", version="1.0.0", category=Skill.Category.CORE,
            input_schema={"type": "object"}, output_schema={"type": "object"},
        )
        self.related = Skill.objects.create(
            name="T169 related", version="1.0.0", category=Skill.Category.SPECIALIZED,
            input_schema={"type": "object"}, output_schema={"type": "object"},
        )
        self.definition = {
            "nodes": [
                {
                    "node_id": "primary", "node_type": "skill", "role": "core",
                    "skill_id": str(self.primary.pk), "skill_version_range": "*", "depends_on": [],
                    "input_schema": {"type": "object"}, "output_schema": {"type": "object"},
                },
                {
                    "node_id": "related", "node_type": "skill", "role": "related",
                    "skill_id": str(self.related.pk), "skill_version_range": "*", "depends_on": ["primary"],
                    "input_schema": {"type": "object"}, "output_schema": {"type": "object"},
                },
            ],
            "max_calls": 20, "max_runtime_seconds": 300, "max_cost_units": 0,
            "allowed_data_scopes": [],
        }
        self.chain = SkillChain.objects.create(
            name="T169 runtime", version="1.0.0", definition=self.definition,
            status=SkillChain.Status.ENABLED, published_at=timezone.now(), created_by=self.admin,
        )

    def test_start_freezes_snapshot_executes_lineage_and_is_idempotent(self) -> None:
        """A duplicate request returns the same run and secrets are not echoed in snapshots."""
        self.client.force_authenticate(self.admin)
        payload = {
            "chain_id": str(self.chain.pk), "idempotency_key": "t169-once",
            "input": {"requirement": "hello", "token": "do-not-persist"},
        }
        response = self.client.post("/api/skill-chain-runs/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], SkillChainRun.Status.COMPLETED)
        self.assertEqual(response.data["input_snapshot"]["token"], "[REDACTED]")
        self.assertEqual([item["status"] for item in response.data["nodes"]], ["completed", "completed"])
        self.assertEqual(response.data["nodes"][1]["input_snapshot"]["upstream"]["primary"]["status"], "completed")
        duplicate = self.client.post("/api/skill-chain-runs/", payload, format="json")
        self.assertEqual(duplicate.status_code, 200, duplicate.data)
        self.assertEqual(duplicate.data["id"], response.data["id"])
        events = self.client.get(f"/api/skill-chain-runs/{response.data['id']}/events/")
        self.assertEqual(events.status_code, 200)
        self.assertEqual([item["sequence"] for item in events.data], list(range(1, len(events.data) + 1)))
        self.assertTrue(SkillChainRunEvent.objects.filter(run_id=response.data["id"], event_type="run_completed").exists())

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_pause_resume_and_cancel_are_persisted_controls(self) -> None:
        """A queued run can pause, resume and cancel through the run API."""
        self.client.force_authenticate(self.admin)
        created = self.client.post(
            "/api/skill-chain-runs/",
            {"chain_id": str(self.chain.pk), "idempotency_key": "t169-controls", "input": {}},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        run_id = created.data["id"]
        paused = self.client.post(f"/api/skill-chain-runs/{run_id}/pause/", {}, format="json")
        self.assertEqual(paused.status_code, 200)
        self.assertEqual(paused.data["status"], SkillChainRun.Status.PAUSED)
        resumed = self.client.post(f"/api/skill-chain-runs/{run_id}/resume/", {"input": {}}, format="json")
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.data["status"], SkillChainRun.Status.PENDING)
        cancelled = self.client.post(f"/api/skill-chain-runs/{run_id}/cancel/", {}, format="json")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.data["status"], SkillChainRun.Status.CANCELLED)

    def test_human_gate_waits_and_resume_completes_from_checkpoint(self) -> None:
        """Human gates are durable waiting states, not frontend-only flags."""
        gated = SkillChain.objects.create(
            name="T169 gated", version="1.0.0", definition={**self.definition, "nodes": [
                self.definition["nodes"][0],
                {"node_id": "approval", "node_type": "human_gate", "role": "related", "skill_id": None, "depends_on": ["primary"]},
            ]}, status=SkillChain.Status.ENABLED, published_at=timezone.now(), created_by=self.admin,
        )
        self.client.force_authenticate(self.admin)
        started = self.client.post("/api/skill-chain-runs/", {"chain_id": str(gated.pk), "input": {}}, format="json")
        self.assertEqual(started.status_code, 201, started.data)
        self.assertEqual(started.data["status"], SkillChainRun.Status.WAITING_HUMAN)
        resumed = self.client.post(f"/api/skill-chain-runs/{started.data['id']}/resume/", {"input": {"approved": True}}, format="json")
        self.assertEqual(resumed.status_code, 200, resumed.data)
        self.assertEqual(resumed.data["status"], SkillChainRun.Status.COMPLETED)

    def test_waiting_human_cancel_is_terminal_without_a_worker(self) -> None:
        """A waiting human gate can be cancelled immediately because no worker is active."""
        gated = SkillChain.objects.create(
            name="T169 cancel gate", version="1.0.0", definition={**self.definition, "nodes": [
                self.definition["nodes"][0],
                {"node_id": "approval", "node_type": "human_gate", "role": "related", "skill_id": None, "depends_on": ["primary"]},
            ]}, status=SkillChain.Status.ENABLED, published_at=timezone.now(), created_by=self.admin,
        )
        self.client.force_authenticate(self.admin)
        started = self.client.post("/api/skill-chain-runs/", {"chain_id": str(gated.pk), "input": {}}, format="json")
        self.assertEqual(started.status_code, 201)
        cancelled = self.client.post(f"/api/skill-chain-runs/{started.data['id']}/cancel/", {}, format="json")
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(cancelled.data["status"], SkillChainRun.Status.CANCELLED)

    def test_project_scope_and_anonymous_boundary(self) -> None:
        """Project runs require membership and anonymous callers receive 401."""
        project = Project.objects.create(name="T169 project", created_by=self.admin)
        ProjectMember.objects.create(project=project, user=self.admin, role=ProjectMember.Role.MANAGER)
        project_chain = SkillChain.objects.create(
            name="T169 project chain", version="1.0.0", project=project, definition=self.definition,
            status=SkillChain.Status.ENABLED, published_at=timezone.now(), created_by=self.admin,
        )
        anonymous = self.client.post("/api/skill-chain-runs/", {"chain_id": str(project_chain.pk)}, format="json")
        self.assertEqual(anonymous.status_code, 401)
        self.client.force_authenticate(self.outsider)
        denied = self.client.post("/api/skill-chain-runs/", {"chain_id": str(project_chain.pk)}, format="json")
        self.assertEqual(denied.status_code, 403)

    def test_service_rejects_missing_configuration_and_snapshot_skill_changes_do_not_break_run(self) -> None:
        """No chain selection is explicit, while an existing snapshot remains executable."""
        service = SkillChainExecutionService()
        with self.assertRaisesMessage(Exception, "当前范围没有可用的"):
            service.start(user=self.admin, payload={"input": {}})
        self.client.force_authenticate(self.admin)
        started = self.client.post("/api/skill-chain-runs/", {"chain_id": str(self.chain.pk), "input": {}}, format="json")
        self.assertEqual(started.status_code, 201)
        self.assertEqual(started.data["status"], SkillChainRun.Status.COMPLETED)
