"""Prompt manager tests for task T012."""

from django.test import TestCase

from apps.configs.models import PromptConfig
from core.prompts.manager import PromptManager


class PromptManagerTests(TestCase):
    def setUp(self) -> None:
        """Keep manager scenarios independent from migration seed data."""
        PromptConfig.objects.all().delete()

    def create_prompt(self, name: str, scope: str, content: str, **overrides: object) -> PromptConfig:
        values: dict[str, object] = {
            "scene_type": PromptConfig.SceneType.API_TEST,
            "variables": {},
        }
        values.update(overrides)
        return PromptConfig.objects.create(
            name=name, scope=scope, content=content, **values
        )

    def test_four_layers_merge_in_instruction_order_and_report_precedence(self) -> None:
        self.create_prompt(
            "platform-default",
            PromptConfig.Scope.GLOBAL,
            "global rules",
            scene_type=PromptConfig.SceneType.DEFAULT,
        )
        self.create_prompt("project-a", PromptConfig.Scope.PROJECT, "project rules")
        self.create_prompt("api-scene", PromptConfig.Scope.SCENE, "scene rules")

        result = PromptManager().resolve(
            PromptConfig.SceneType.API_TEST,
            project_name="project-a",
            instant_prompt="instant rules",
        )

        self.assertEqual(
            result.content,
            "global rules\n\nproject rules\n\nscene rules\n\ninstant rules",
        )
        self.assertEqual(result.layers, ("instant", "scene", "project", "global"))

    def test_latest_active_version_is_selected(self) -> None:
        self.create_prompt("api-scene", PromptConfig.Scope.SCENE, "v1", version=1)
        inactive = self.create_prompt(
            "api-scene", PromptConfig.Scope.SCENE, "v3", version=3
        )
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        selected = self.create_prompt(
            "api-scene", PromptConfig.Scope.SCENE, "v2", version=2
        )

        result = PromptManager().resolve(PromptConfig.SceneType.API_TEST)

        self.assertEqual(result.content, "v2")
        self.assertEqual(result.config_ids, (selected.pk,))

    def test_project_prompt_is_isolated_by_name(self) -> None:
        self.create_prompt("project-a", PromptConfig.Scope.PROJECT, "A")
        self.create_prompt("project-b", PromptConfig.Scope.PROJECT, "B")

        result = PromptManager().resolve(
            PromptConfig.SceneType.API_TEST, project_name="project-b"
        )

        self.assertEqual(result.content, "B")

    def test_higher_priority_variables_override_lower_priority_values(self) -> None:
        self.create_prompt(
            "platform-default",
            PromptConfig.Scope.GLOBAL,
            "global",
            scene_type=PromptConfig.SceneType.DEFAULT,
            variables={"language": "English", "tone": "neutral"},
        )
        self.create_prompt(
            "api-scene",
            PromptConfig.Scope.SCENE,
            "scene",
            variables={"language": "中文"},
        )

        result = PromptManager().resolve(PromptConfig.SceneType.API_TEST)

        self.assertEqual(dict(result.variables), {"language": "中文", "tone": "neutral"})

    def test_no_configuration_returns_builtin_default(self) -> None:
        manager = PromptManager(default_prompt="safe fallback")

        result = manager.resolve(PromptConfig.SceneType.CASE_GEN)

        self.assertEqual(result.content, "safe fallback")
        self.assertEqual(result.layers, ("default",))
        self.assertEqual(result.config_ids, ())

    def test_get_prompt_returns_plain_content(self) -> None:
        self.create_prompt("ai-scene", PromptConfig.Scope.SCENE, "evaluate safely", scene_type=PromptConfig.SceneType.AI_TEST)

        content = PromptManager().get_prompt(PromptConfig.SceneType.AI_TEST)

        self.assertEqual(content, "evaluate safely")

    def test_unknown_scene_type_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PromptManager().resolve("unknown-scene")
