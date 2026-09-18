"""Platform-role and project-role matrix tests for agent APIs."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.agents.models import Agent
from apps.agents.permissions import can_edit_agents, can_execute_agent
from apps.configs.models import ModelConfig
from apps.projects.models import Project, ProjectMember
from apps.users.models import UserProfile


class AgentPermissionMatrixTests(TestCase):
    """Ensure agent operations require both layers of authorization."""

    def setUp(self) -> None:
        user_model = get_user_model()
        self.leader = user_model.objects.create_user(username="agent-perm-leader")
        self.tester = user_model.objects.create_user(username="agent-perm-tester")
        self.developer = user_model.objects.create_user(username="agent-perm-developer")
        self.viewer = user_model.objects.create_user(username="agent-perm-viewer")
        for user, role in (
            (self.leader, UserProfile.Role.TEST_LEADER),
            (self.tester, UserProfile.Role.TESTER),
            (self.developer, UserProfile.Role.DEVELOPER),
            (self.viewer, UserProfile.Role.VIEWER),
        ):
            user.profile.role = role
            user.profile.save(update_fields=("role",))
        self.project = Project.objects.create(
            name="Agent permission project", created_by=self.leader
        )
        for user, role in (
            (self.leader, ProjectMember.Role.OWNER),
            (self.tester, ProjectMember.Role.MANAGER),
            (self.developer, ProjectMember.Role.MEMBER),
            (self.viewer, ProjectMember.Role.MANAGER),
        ):
            ProjectMember.objects.create(project=self.project, user=user, role=role)
        model = ModelConfig.objects.create(
            name="Agent permission model", provider="custom", model_name="mock"
        )
        self.agent = Agent.objects.create(
            project=self.project,
            name="Permission agent",
            model_config=model,
            created_by=self.tester,
            status=Agent.Status.ACTIVE,
        )

    def test_create_requires_create_agent_capability(self) -> None:
        """A viewer cannot create an agent merely by being a project manager."""
        self.assertTrue(can_edit_agents(self.leader, self.project))
        self.assertFalse(can_edit_agents(self.tester, self.project))
        self.assertFalse(can_edit_agents(self.viewer, self.project))

    def test_execute_honors_global_and_own_module_scopes(self) -> None:
        """Testers execute project agents; developers execute only their own agent."""
        self.assertTrue(can_execute_agent(self.tester, self.agent))
        self.assertFalse(can_execute_agent(self.developer, self.agent))
        self.assertFalse(can_execute_agent(self.viewer, self.agent))
        own_agent = Agent.objects.create(
            project=self.project,
            name="Developer-owned agent",
            model_config=self.agent.model_config,
            created_by=self.developer,
            status=Agent.Status.ACTIVE,
        )
        self.assertTrue(can_execute_agent(self.developer, own_agent))
