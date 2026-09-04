"""Backend contract additions required by the T114 workspace UI."""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.agents.models import Agent
from apps.configs.models import ModelConfig
from apps.projects.models import Project, ProjectMember


class ProjectAgentFrontendContractTests(APITestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="t114-owner")
        self.candidate = users.objects.create_user(username="t114-candidate")
        self.outsider = users.objects.create_user(username="t114-outsider")
        self.project = Project.objects.create(name="T114 Project", created_by=self.owner)
        ProjectMember.objects.create(
            project=self.project, user=self.owner, role=ProjectMember.Role.OWNER
        )
        self.model_config = ModelConfig.objects.create(
            name="T114 Model", provider="openai", model_name="mock"
        )

    def test_owner_receives_safe_member_candidates_but_outsider_does_not(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(
            f"/api/projects/{self.project.id}/member-candidates/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["username"] for item in response.data],
            [self.candidate.username, self.outsider.username],
        )
        self.assertNotIn("password", response.data[0])

        self.client.force_authenticate(self.outsider)
        hidden = self.client.get(f"/api/projects/{self.project.id}/member-candidates/")
        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)

    def test_agent_response_exposes_project_id_for_workspace_state(self):
        Agent.objects.create(
            project=self.project,
            name="T114 Agent",
            model_config=self.model_config,
            created_by=self.owner,
        )
        self.client.force_authenticate(self.owner)
        response = self.client.get("/api/agents/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data[0]["project_id"], self.project.id)
