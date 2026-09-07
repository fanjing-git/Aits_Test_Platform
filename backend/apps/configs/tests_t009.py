"""Model manager tests for task T009."""

from django.test import TestCase

from apps.configs.models import ModelConfig
from core.llm.manager import (
    ModelFactoryNotConfigured,
    ModelFallbackExhausted,
    ModelManager,
    ModelNotFound,
)


class FakeRuntime:
    """Small non-network runtime used to verify routing behavior."""

    def __init__(self, name: str) -> None:
        self.name = name


class ModelManagerTests(TestCase):
    def create_config(self, name: str, **overrides: object) -> ModelConfig:
        values: dict[str, object] = {
            "provider": ModelConfig.Provider.LOCAL,
            "model_name": name,
            "model_type": ModelConfig.ModelType.CHAT,
            "priority": 100,
        }
        values.update(overrides)
        return ModelConfig.objects.create(name=name, **values)

    @staticmethod
    def factory(config: ModelConfig) -> FakeRuntime:
        return FakeRuntime(config.name)

    def test_load_excludes_inactive_and_ranks_default_before_priority(self) -> None:
        self.create_config("priority-first", priority=1)
        self.create_config("default-model", priority=99, is_default=True)
        self.create_config("inactive", priority=0, is_active=False)

        manager = ModelManager(self.factory)

        self.assertEqual(
            [config.name for config in manager.candidates("chat")],
            ["default-model", "priority-first"],
        )

    def test_routes_task_types_to_required_capability(self) -> None:
        self.create_config("chat-model")
        self.create_config(
            "embedding-model", model_type=ModelConfig.ModelType.EMBEDDING
        )
        self.create_config("vision-model", model_type=ModelConfig.ModelType.VISION)
        manager = ModelManager(self.factory)

        self.assertEqual(manager.get_config("requirement_analysis").name, "chat-model")
        self.assertEqual(manager.get_config("retrieval").name, "embedding-model")
        self.assertEqual(manager.get_config("screenshot").name, "vision-model")

    def test_text_analysis_can_use_default_multimodal_or_vision_model(self) -> None:
        self.create_config("chat-model", priority=1)
        self.create_config("qwen-vision", model_type=ModelConfig.ModelType.VISION, is_default=True, priority=50)
        manager = ModelManager(self.factory)
        self.assertEqual(manager.get_config("requirement_analysis").name, "qwen-vision")
        self.assertEqual(manager.get_config("case_gen").name, "qwen-vision")

    def test_switch_changes_only_the_matching_model_type(self) -> None:
        self.create_config("primary", priority=1)
        self.create_config("secondary", priority=2)
        manager = ModelManager(self.factory)

        manager.switch("secondary")

        self.assertEqual(manager.get_config("chat").name, "secondary")

    def test_preferred_model_overrides_switch_for_one_route(self) -> None:
        self.create_config("primary", priority=1)
        self.create_config("secondary", priority=2)
        manager = ModelManager(self.factory)
        manager.switch("secondary")

        chosen = manager.get_config("chat", preferred_name="primary")

        self.assertEqual(chosen.name, "primary")
        self.assertEqual(manager.get_config("chat").name, "secondary")

    def test_runtime_instances_are_cached_per_configuration(self) -> None:
        calls: list[str] = []
        self.create_config("cached")

        def recording_factory(config: ModelConfig) -> FakeRuntime:
            calls.append(config.name)
            return FakeRuntime(config.name)

        manager = ModelManager(recording_factory)

        self.assertIs(manager.get_model("chat"), manager.get_model("chat"))
        self.assertEqual(calls, ["cached"])

    def test_failure_automatically_uses_the_next_model(self) -> None:
        self.create_config("primary", priority=1)
        self.create_config("fallback", priority=2)
        manager = ModelManager(self.factory)

        def operation(runtime: FakeRuntime, config: ModelConfig) -> str:
            if config.name == "primary":
                raise TimeoutError("simulated provider timeout")
            return runtime.name

        result = manager.execute_with_fallback("chat", operation)

        self.assertEqual(result, "fallback")

    def test_all_failures_raise_sanitized_error_with_attempt_order(self) -> None:
        self.create_config("primary", priority=1)
        self.create_config("fallback", priority=2)
        manager = ModelManager(self.factory)

        with self.assertRaises(ModelFallbackExhausted) as raised:
            manager.execute_with_fallback(
                "chat", lambda runtime, config: (_ for _ in ()).throw(OSError("secret"))
            )

        self.assertEqual(raised.exception.attempted_models, ("primary", "fallback"))
        self.assertNotIn("secret", str(raised.exception))

    def test_missing_model_and_factory_fail_explicitly(self) -> None:
        manager = ModelManager()
        with self.assertRaises(ModelNotFound):
            manager.get_config("vision")

        self.create_config("chat-model")
        manager.load()
        with self.assertRaises(ModelFactoryNotConfigured):
            manager.get_model("chat")
