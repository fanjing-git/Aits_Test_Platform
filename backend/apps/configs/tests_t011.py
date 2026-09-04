"""Model tests for task T011."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.configs.models import PromptConfig


class PromptConfigTests(TestCase):
    """Verify hierarchical, versioned prompt configuration persistence."""

    def setUp(self) -> None:
        """Keep model-contract tests independent from seeded prompt data."""
        PromptConfig.objects.all().delete()

    def test_multiple_prompt_scopes_can_be_created(self) -> None:
        prompts = [
            PromptConfig.objects.create(
                name=f"prompt-{scope}",
                scope=scope,
                scene_type=PromptConfig.SceneType.API_TEST,
                content=f"content for {scope}",
            )
            for scope in PromptConfig.Scope.values
        ]

        self.assertEqual(len(prompts), 4)
        self.assertEqual(
            set(PromptConfig.objects.values_list("scope", flat=True)),
            set(PromptConfig.Scope.values),
        )

    def test_defaults_and_template_variables_are_persisted(self) -> None:
        prompt = PromptConfig.objects.create(
            name="default-agent",
            scope=PromptConfig.Scope.GLOBAL,
            content="You are a {{ role }}.",
            variables={"role": "testing assistant"},
        )

        self.assertEqual(prompt.scene_type, PromptConfig.SceneType.DEFAULT)
        self.assertEqual(prompt.variables, {"role": "testing assistant"})
        self.assertEqual(prompt.version, 1)
        self.assertTrue(prompt.is_active)

    def test_invalid_choices_variables_and_version_are_rejected(self) -> None:
        prompt = PromptConfig(
            name="invalid",
            scope="unsupported",
            scene_type="unsupported",
            content="content",
            variables=["not", "an", "object"],
            version=0,
        )

        with self.assertRaises(ValidationError):
            prompt.full_clean()

    def test_prompt_versions_coexist_but_duplicates_are_rejected(self) -> None:
        values = {
            "name": "api-standard",
            "scope": PromptConfig.Scope.SCENE,
            "scene_type": PromptConfig.SceneType.API_TEST,
            "content": "Generate API tests.",
        }
        PromptConfig.objects.create(**values, version=1)
        PromptConfig.objects.create(**values, version=2)

        self.assertEqual(
            list(PromptConfig.objects.values_list("version", flat=True)), [2, 1]
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            PromptConfig.objects.create(**values, version=2)
