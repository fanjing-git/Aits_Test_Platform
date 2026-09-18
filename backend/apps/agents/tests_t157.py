"""T157 tests for controlled model execution, permissions, and recovery."""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.agents.models import Agent, AgentExecution
from apps.configs.models import ModelConfig
from apps.projects.models import Project, ProjectMember
from apps.users.models import UserProfile


class AgentExecutionApiTests(APITestCase):
    """Cover the REST-to-model-to-audit execution path."""

    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="t157-owner")
        self.member = users.objects.create_user(username="t157-member")
        self.viewer = users.objects.create_user(username="t157-viewer")
        self.outsider = users.objects.create_user(username="t157-outsider")
        for user, platform_role in (
            (self.owner, UserProfile.Role.TEST_LEADER),
            (self.member, UserProfile.Role.TESTER),
        ):
            user.profile.role = platform_role
            user.profile.save(update_fields=("role",))
        self.project = Project.objects.create(name="T157 Project", created_by=self.owner)
        for user, role in (
            (self.owner, ProjectMember.Role.OWNER),
            (self.member, ProjectMember.Role.MEMBER),
            (self.viewer, ProjectMember.Role.VIEWER),
        ):
            ProjectMember.objects.create(project=self.project, user=user, role=role)
        self.model = ModelConfig.objects.create(
            name="T157 Mock Model",
            provider=ModelConfig.Provider.CUSTOM,
            model_name="mock-model",
            model_type=ModelConfig.ModelType.CHAT,
        )
        self.agent = Agent.objects.create(
            project=self.project,
            name="T157 Agent",
            model_config=self.model,
            created_by=self.owner,
            status=Agent.Status.ACTIVE,
            parameters={"allowed_tools": []},
        )
        self.url = f"/api/agents/{self.agent.pk}/execute/"

    @staticmethod
    def provider_response(payload):
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    def test_member_can_execute_and_receives_safe_audit(self):
        self.client.force_authenticate(self.member)
        with patch("apps.agents.execution.structured_chat", return_value=self.provider_response({"answer": "done"})) as call:
            response = self.client.post(self.url, {"input_text": "Summarize this test run."}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["status"], AgentExecution.Status.COMPLETED)
        self.assertEqual(response.data["result"]["answer"], "done")
        self.assertEqual(response.data["model_route"]["candidates"][0]["name"], self.model.name)
        self.assertNotIn("api_key", json.dumps(response.data).lower())
        messages = call.call_args.kwargs["messages"]
        self.assertNotIn("api_key_encrypted", json.dumps(messages))

    def test_unauthorized_tool_is_blocked_and_audited(self):
        self.client.force_authenticate(self.owner)
        payload = {"tool_calls": [{"name": "delete_project", "arguments": {}}]}
        with patch("apps.agents.execution.structured_chat", return_value=self.provider_response(payload)):
            response = self.client.post(self.url, {"input_text": "Delete the project."}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], AgentExecution.Status.FAILED)
        self.assertEqual(response.data["error_code"], "tool_not_authorized")
        self.assertFalse(response.data["retryable"])

    def test_pause_preflight_and_resume_use_the_same_endpoint_contract(self):
        self.client.force_authenticate(self.owner)
        paused = self.client.post(
            self.url,
            {"input_text": "Pause before starting.", "interrupt_signal": "pause"},
            format="json",
        )
        self.assertEqual(paused.status_code, status.HTTP_201_CREATED)
        self.assertEqual(paused.data["status"], AgentExecution.Status.PAUSED)
        execution_url = f"/api/agent-executions/{paused.data['id']}"
        with patch("apps.agents.execution.structured_chat", return_value=self.provider_response({"answer": "resumed"})):
            resumed = self.client.post(f"{execution_url}/resume/", format="json")
        self.assertEqual(resumed.status_code, status.HTTP_200_OK, resumed.data)
        self.assertEqual(resumed.data["status"], AgentExecution.Status.COMPLETED)

    def test_field_auth_and_visibility_boundaries(self):
        self.client.force_authenticate(self.member)
        invalid = self.client.post(self.url, {"input_text": ""}, format="json")
        self.assertEqual(invalid.status_code, status.HTTP_400_BAD_REQUEST)

        self.client.force_authenticate(self.viewer)
        denied = self.client.post(self.url, {"input_text": "run"}, format="json")
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.outsider)
        hidden = self.client.get(f"/api/agent-executions/?agent={self.agent.pk}")
        self.assertEqual(hidden.status_code, status.HTTP_200_OK)
        self.assertEqual(hidden.data, [])

        self.client.force_authenticate(None)
        anonymous = self.client.post(self.url, {"input_text": "run"}, format="json")
        self.assertEqual(anonymous.status_code, status.HTTP_401_UNAUTHORIZED)
