"""T018 API tests for project-scoped versioned agents."""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.agents.models import Agent
from apps.configs.models import ModelConfig, PromptConfig
from apps.projects.models import Project, ProjectMember


class AgentApiTests(APITestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="agent-api-owner")
        self.manager = users.objects.create_user(username="agent-api-manager")
        self.member = users.objects.create_user(username="agent-api-member")
        self.outsider = users.objects.create_user(username="agent-api-outsider")
        self.admin = users.objects.create_user(username="agent-api-admin")
        self.admin.profile.role = "admin"
        self.admin.profile.save(update_fields=["role"])
        self.project = Project.objects.create(name="Agent API Project", created_by=self.owner)
        for user, role in (
            (self.owner, ProjectMember.Role.OWNER),
            (self.manager, ProjectMember.Role.MANAGER),
            (self.member, ProjectMember.Role.MEMBER),
        ):
            ProjectMember.objects.create(project=self.project, user=user, role=role)
        self.model_config = ModelConfig.objects.create(
            name="Agent API Model", provider="openai", model_name="mock-model"
        )
        self.prompt_config = PromptConfig.objects.create(
            name="Agent API Prompt", scope="project", content="test prompt"
        )
        self.url = "/api/agents/"

    def payload(self, **overrides):
        data = {
            "project_id": str(self.project.id),
            "name": "API Agent",
            "description": "v1",
            "agent_type": "test_executor",
            "model_config_id": self.model_config.pk,
            "prompt_config_id": self.prompt_config.pk,
            "knowledge_base_ids": ["kb-one"],
            "skill_ids": ["api-test"],
            "parameters": {"max_steps": 5},
            "status": "active",
        }
        data.update(overrides)
        return data

    def create_agent(self, user=None):
        self.client.force_authenticate(user or self.owner)
        response = self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response

    def test_owner_can_create_and_member_can_read(self):
        created = self.create_agent()
        self.assertEqual(created.data["version"], 1)
        self.assertEqual(created.data["created_by"]["username"], self.owner.username)

        self.client.force_authenticate(self.member)
        response = self.client.get(self.url, {"project": self.project.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_manager_update_creates_new_version_and_default_list_is_latest(self):
        created = self.create_agent()
        self.client.force_authenticate(self.manager)
        response = self.client.patch(
            f"{self.url}{created.data['id']}/",
            {"description": "v2", "parameters": {"max_steps": 8}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["version"], 2)
        self.assertEqual(Agent.objects.count(), 2)

        latest = self.client.get(self.url)
        all_versions = self.client.get(self.url, {"include_history": "true"})
        self.assertEqual([item["version"] for item in latest.data], [2])
        self.assertEqual({item["version"] for item in all_versions.data}, {1, 2})

    def test_history_and_rollback_create_an_auditable_new_version(self):
        created = self.create_agent()
        self.client.patch(
            f"{self.url}{created.data['id']}/",
            {"description": "v2"},
            format="json",
        )
        latest = Agent.objects.get(project=self.project, name="API Agent", version=2)
        history = self.client.get(f"{self.url}{latest.id}/history/")
        self.assertEqual([item["version"] for item in history.data], [2, 1])

        rollback = self.client.post(
            f"{self.url}{latest.id}/rollback/", {"version": 1}, format="json"
        )
        self.assertEqual(rollback.status_code, status.HTTP_201_CREATED, rollback.data)
        self.assertEqual(rollback.data["version"], 3)
        self.assertEqual(rollback.data["description"], "v1")

    def test_member_is_read_only_and_outsider_cannot_discover_agents(self):
        created = self.create_agent()
        self.client.force_authenticate(self.member)
        denied = self.client.patch(
            f"{self.url}{created.data['id']}/", {"description": "forbidden"}
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.url).data, [])
        hidden = self.client.get(f"{self.url}{created.data['id']}/")
        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)
        create_denied = self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(create_denied.status_code, status.HTTP_403_FORBIDDEN)

    def test_only_owner_or_platform_admin_can_delete_the_lineage(self):
        created = self.create_agent()
        self.client.patch(
            f"{self.url}{created.data['id']}/", {"description": "v2"}, format="json"
        )
        latest = Agent.objects.get(version=2)
        self.client.force_authenticate(self.manager)
        denied = self.client.delete(f"{self.url}{latest.id}/")
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.admin)
        deleted = self.client.delete(f"{self.url}{latest.id}/")
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Agent.objects.count(), 0)

    def test_duplicate_name_in_project_is_rejected(self):
        self.create_agent()
        duplicate = self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)

    def test_inactive_configs_invalid_json_and_anonymous_are_rejected(self):
        self.client.force_authenticate(self.owner)
        invalid_json = self.client.post(
            self.url, self.payload(parameters=[]), format="json"
        )
        self.assertEqual(invalid_json.status_code, status.HTTP_400_BAD_REQUEST)

        self.model_config.is_active = False
        self.model_config.save(update_fields=["is_active"])
        inactive = self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(inactive.status_code, status.HTTP_400_BAD_REQUEST)

        self.client.force_authenticate(None)
        anonymous = self.client.get(self.url)
        self.assertEqual(anonymous.status_code, status.HTTP_401_UNAUTHORIZED)
