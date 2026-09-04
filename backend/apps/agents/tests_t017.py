"""T017 model coverage for project-scoped agent configurations."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.agents.models import Agent
from apps.configs.models import ModelConfig, PromptConfig
from apps.projects.models import Project


class AgentModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="agent-owner", password="safe-test-password"
        )
        self.project = Project.objects.create(name="Agent Project", created_by=self.user)
        self.model_config = ModelConfig.objects.create(
            name="Agent Model",
            provider=ModelConfig.Provider.OPENAI,
            model_name="mock-model",
        )
        self.prompt_config = PromptConfig.objects.create(
            name="Agent Prompt",
            scope=PromptConfig.Scope.PROJECT,
            content="You are a test agent.",
        )

    def make_agent(self, **overrides):
        values = {
            "project": self.project,
            "name": "QA Agent",
            "model_config": self.model_config,
            "prompt_config": self.prompt_config,
            "created_by": self.user,
        }
        values.update(overrides)
        return Agent.objects.create(**values)

    def test_create_complete_agent_configuration(self):
        agent = self.make_agent(
            agent_type=Agent.AgentType.TEST_EXECUTOR,
            status=Agent.Status.ACTIVE,
            knowledge_base_ids=["kb-product", "kb-rules"],
            skill_ids=["api-test", "case-review"],
            parameters={"temperature": 0.2, "max_steps": 12},
        )

        self.assertEqual(agent.version, 1)
        self.assertEqual(agent.project, self.project)
        self.assertEqual(agent.model_config, self.model_config)
        self.assertEqual(agent.prompt_config, self.prompt_config)
        self.assertEqual(agent.knowledge_base_ids, ["kb-product", "kb-rules"])

    def test_default_values_are_safe_and_independent(self):
        first = self.make_agent(name="First")
        second = self.make_agent(name="Second")
        first.skill_ids.append("api-test")

        self.assertEqual(first.status, Agent.Status.DRAFT)
        self.assertEqual(first.agent_type, Agent.AgentType.GENERAL)
        self.assertEqual(second.skill_ids, [])
        self.assertEqual(second.parameters, {})

    def test_same_name_and_version_is_unique_inside_project(self):
        self.make_agent()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_agent()

        other_project = Project.objects.create(name="Other Project", created_by=self.user)
        self.make_agent(project=other_project)
        self.make_agent(version=2)
        self.assertEqual(Agent.objects.filter(name="QA Agent").count(), 3)

    def test_json_reference_and_parameter_validation(self):
        invalid_values = (
            {"knowledge_base_ids": "kb-product"},
            {"skill_ids": ["api-test", "api-test"]},
            {"skill_ids": [""]},
            {"parameters": []},
        )
        for index, overrides in enumerate(invalid_values):
            with self.subTest(overrides=overrides):
                agent = Agent(
                    project=self.project,
                    name=f"Invalid {index}",
                    model_config=self.model_config,
                    created_by=self.user,
                    **overrides,
                )
                with self.assertRaises(ValidationError):
                    agent.full_clean()

    def test_deletion_rules_preserve_configuration_auditability(self):
        agent = self.make_agent()
        self.prompt_config.delete()
        agent.refresh_from_db()
        self.assertIsNone(agent.prompt_config)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.model_config.delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.user.delete()

        self.project.delete()
        self.assertFalse(Agent.objects.filter(pk=agent.pk).exists())
