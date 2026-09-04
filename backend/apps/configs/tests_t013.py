"""Default prompt tests for task T013."""

from django.test import TestCase

from apps.configs.models import PromptConfig
from core.prompts.defaults import DEFAULT_PROMPTS, install_default_prompts
from core.prompts.manager import PromptManager


class DefaultPromptTests(TestCase):
    def setUp(self) -> None:
        PromptConfig.objects.all().delete()

    def test_all_eleven_scenes_are_installed(self) -> None:
        installed = install_default_prompts()

        self.assertEqual(len(installed), 11)
        self.assertEqual(len(DEFAULT_PROMPTS), 11)
        self.assertEqual(
            set(PromptConfig.objects.values_list("scene_type", flat=True)),
            set(PromptConfig.SceneType.values),
        )

    def test_installation_is_idempotent_and_preserves_local_edits(self) -> None:
        install_default_prompts()
        prompt = PromptConfig.objects.get(name="api-test-default")
        prompt.content = "locally reviewed content"
        prompt.save(update_fields=("content", "updated_at"))

        install_default_prompts()

        self.assertEqual(PromptConfig.objects.count(), 11)
        prompt.refresh_from_db()
        self.assertEqual(prompt.content, "locally reviewed content")

    def test_each_default_is_active_nonempty_and_has_object_variables(self) -> None:
        installed = install_default_prompts()

        for prompt in installed:
            with self.subTest(scene=prompt.scene_type):
                self.assertTrue(prompt.is_active)
                self.assertTrue(prompt.content.strip())
                self.assertIsInstance(prompt.variables, dict)
                prompt.full_clean()

    def test_manager_combines_global_identity_with_scene_instructions(self) -> None:
        install_default_prompts()

        result = PromptManager().resolve(PromptConfig.SceneType.API_TEST)

        self.assertEqual(result.layers, ("scene", "global"))
        self.assertIn("质量工程助手", result.content)
        self.assertIn("pytest", result.content)
