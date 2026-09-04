"""Resolve active prompt configurations through the four-tier hierarchy."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from apps.configs.models import PromptConfig


@dataclass(frozen=True)
class ResolvedPrompt:
    """Immutable prompt result plus provenance for auditing and later APIs."""

    content: str
    variables: Mapping[str, object]
    layers: tuple[str, ...]
    config_ids: tuple[int, ...]


class PromptManager:
    """Merge global, project, scene, and immediate prompt instructions."""

    DEFAULT_PROMPT = (
        "你是 AI 智能体测试平台的质量助手。请基于用户输入提供准确、可验证的结果。"
    )
    SEPARATOR = "\n\n"

    def __init__(self, default_prompt: str | None = None) -> None:
        self.default_prompt = default_prompt or self.DEFAULT_PROMPT

    def get_prompt(
        self,
        scene_type: str = PromptConfig.SceneType.DEFAULT,
        *,
        project_name: str | None = None,
        instant_prompt: str | None = None,
    ) -> str:
        """Return only the merged text for the common runtime call path."""
        return self.resolve(
            scene_type,
            project_name=project_name,
            instant_prompt=instant_prompt,
        ).content

    def resolve(
        self,
        scene_type: str = PromptConfig.SceneType.DEFAULT,
        *,
        project_name: str | None = None,
        instant_prompt: str | None = None,
    ) -> ResolvedPrompt:
        """Resolve and merge layers from low to high priority.

        Higher-priority instructions are appended later so that model runtimes
        encounter them last. ``layers`` is reported from high to low priority.
        """
        self._validate_scene_type(scene_type)
        configs: list[PromptConfig] = []

        global_config = self._latest(
            PromptConfig.Scope.GLOBAL, PromptConfig.SceneType.DEFAULT
        )
        if global_config:
            configs.append(global_config)

        if project_name:
            project_config = self._latest(
                PromptConfig.Scope.PROJECT, scene_type, name=project_name
            )
            if project_config:
                configs.append(project_config)

        scene_config = self._latest(PromptConfig.Scope.SCENE, scene_type)
        if scene_config:
            configs.append(scene_config)

        content_parts = [config.content.strip() for config in configs if config.content.strip()]
        normalized_instant = (instant_prompt or "").strip()
        if normalized_instant:
            content_parts.append(normalized_instant)

        if not content_parts:
            return ResolvedPrompt(
                content=self.default_prompt,
                variables=MappingProxyType({}),
                layers=("default",),
                config_ids=(),
            )

        variables: dict[str, object] = {}
        for config in configs:
            variables.update(config.variables)

        low_to_high_layers = [config.scope for config in configs]
        if normalized_instant:
            low_to_high_layers.append(PromptConfig.Scope.INSTANT)

        return ResolvedPrompt(
            content=self.SEPARATOR.join(content_parts),
            variables=MappingProxyType(variables),
            layers=tuple(reversed(low_to_high_layers)),
            config_ids=tuple(config.pk for config in configs),
        )

    @staticmethod
    def _latest(
        scope: str, scene_type: str, *, name: str | None = None
    ) -> PromptConfig | None:
        queryset = PromptConfig.objects.filter(
            scope=scope, scene_type=scene_type, is_active=True
        )
        if name is not None:
            queryset = queryset.filter(name=name)
        return queryset.order_by("-version", "-updated_at", "-pk").first()

    @staticmethod
    def _validate_scene_type(scene_type: str) -> None:
        if scene_type not in PromptConfig.SceneType.values:
            raise ValueError(f"Unsupported prompt scene type: {scene_type}")
