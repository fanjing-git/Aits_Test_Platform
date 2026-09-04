"""REST serializers for model configuration management."""

from typing import Any

from django.db import transaction
from django.db.models import Max
from rest_framework import serializers

from apps.configs.models import ModelConfig, PromptConfig


class ModelConfigSerializer(serializers.ModelSerializer):
    """Expose configuration metadata while accepting API keys write-only."""

    api_key = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
    )
    has_api_key = serializers.SerializerMethodField()

    class Meta:
        model = ModelConfig
        fields = (
            "id",
            "name",
            "provider",
            "model_name",
            "model_type",
            "api_key",
            "has_api_key",
            "api_base_url",
            "parameters",
            "is_default",
            "is_active",
            "priority",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "has_api_key", "created_at", "updated_at")

    def get_has_api_key(self, obj: ModelConfig) -> bool:
        return bool(obj.api_key_encrypted)

    @transaction.atomic
    def create(self, validated_data: dict[str, Any]) -> ModelConfig:
        api_key = validated_data.pop("api_key", None)
        config = ModelConfig(**validated_data)
        if api_key is not None:
            config.set_api_key(api_key)
        config.save()
        self._clear_other_defaults(config)
        return config

    @transaction.atomic
    def update(
        self,
        instance: ModelConfig,
        validated_data: dict[str, Any],
    ) -> ModelConfig:
        api_key = validated_data.pop("api_key", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if api_key is not None:
            instance.set_api_key(api_key)
        instance.save()
        self._clear_other_defaults(instance)
        return instance

    @staticmethod
    def _clear_other_defaults(config: ModelConfig) -> None:
        if config.is_default:
            ModelConfig.objects.filter(
                model_type=config.model_type,
                is_default=True,
            ).exclude(pk=config.pk).update(is_default=False)


class PromptConfigSerializer(serializers.ModelSerializer):
    """Create immutable prompt versions while exposing safe configuration data."""

    scope_label = serializers.CharField(source="get_scope_display", read_only=True)
    scene_type_label = serializers.CharField(
        source="get_scene_type_display", read_only=True
    )

    class Meta:
        model = PromptConfig
        fields = (
            "id",
            "name",
            "scope",
            "scope_label",
            "scene_type",
            "scene_type_label",
            "content",
            "variables",
            "version",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "scope_label",
            "scene_type_label",
            "version",
            "created_at",
            "updated_at",
        )

    @transaction.atomic
    def create(self, validated_data: dict[str, Any]) -> PromptConfig:
        version = self._next_version(
            validated_data["name"],
            validated_data["scope"],
            validated_data.get("scene_type", PromptConfig.SceneType.DEFAULT),
        )
        config = PromptConfig.objects.create(**validated_data, version=version)
        self._deactivate_other_versions(config)
        return config

    @transaction.atomic
    def update(
        self,
        instance: PromptConfig,
        validated_data: dict[str, Any],
    ) -> PromptConfig:
        values = {
            "name": instance.name,
            "scope": instance.scope,
            "scene_type": instance.scene_type,
            "content": instance.content,
            "variables": instance.variables,
            "is_active": instance.is_active,
        }
        values.update(validated_data)
        values["version"] = self._next_version(
            values["name"], values["scope"], values["scene_type"]
        )
        PromptConfig.objects.filter(pk=instance.pk).update(is_active=False)
        config = PromptConfig.objects.create(**values)
        self._deactivate_other_versions(config)
        return config

    @staticmethod
    def _next_version(name: str, scope: str, scene_type: str) -> int:
        current = PromptConfig.objects.filter(
            name=name, scope=scope, scene_type=scene_type
        ).aggregate(latest=Max("version"))["latest"]
        return (current or 0) + 1

    @staticmethod
    def _deactivate_other_versions(config: PromptConfig) -> None:
        if config.is_active:
            PromptConfig.objects.filter(
                name=config.name,
                scope=config.scope,
                scene_type=config.scene_type,
                is_active=True,
            ).exclude(pk=config.pk).update(is_active=False)
