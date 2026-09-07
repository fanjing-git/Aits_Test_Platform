"""REST serializers for model configuration management."""

from typing import Any

from django.db import transaction
from django.db.models import Max
from rest_framework import serializers

from apps.configs.models import ModelConfig, ModelRoutingPolicy, PromptConfig
from apps.configs.services import ProviderError, canonical_base
from apps.configs.routing import required_model_types


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
        """Expose only whether a key is stored."""
        return bool(obj.api_key_encrypted)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Do not silently send an old credential to a changed provider address."""
        provider = attrs.get("provider", self.instance.provider if self.instance else "openai")
        base = attrs.get("api_base_url", self.instance.api_base_url if self.instance else "")
        try:
            if base:
                canonical_base(provider, base)
            if self.instance and self.instance.api_key_encrypted and "api_key" not in attrs:
                changed = provider != self.instance.provider or base != self.instance.api_base_url
                if changed:
                    raise serializers.ValidationError({"api_key": "切换供应商或 API 地址后，请重新填写密钥，避免误用原凭据。"})
        except ProviderError as exc:
            raise serializers.ValidationError({"api_base_url": str(exc)}) from exc
        return attrs

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


class ModelDiscoverySerializer(serializers.Serializer):
    """Validate draft discovery inputs; API keys never appear in responses."""

    provider = serializers.ChoiceField(choices=ModelConfig.Provider.choices)
    api_base_url = serializers.CharField(max_length=500, allow_blank=True, default="")
    api_key = serializers.CharField(max_length=4096, allow_blank=True, required=False, write_only=True)
    config_id = serializers.IntegerField(min_value=1, required=False)
    cursor = serializers.CharField(max_length=2000, allow_blank=True, default="")


class ConnectionModeSerializer(serializers.Serializer):
    """Require an explicit mode before making a possibly billable inference call."""

    mode = serializers.ChoiceField(choices=("catalog", "inference"), default="catalog")


class SafeModelSummarySerializer(serializers.ModelSerializer):
    """Expose selectable model metadata without credentials or parameters."""

    provider_label = serializers.CharField(source="get_provider_display", read_only=True)
    model_type_label = serializers.CharField(source="get_model_type_display", read_only=True)

    class Meta:
        model = ModelConfig
        fields = (
            "id",
            "name",
            "provider",
            "provider_label",
            "model_name",
            "model_type",
            "model_type_label",
            "is_default",
            "is_active",
            "priority",
        )


class ModelRoutingPolicySerializer(serializers.ModelSerializer):
    """Validate and expose one global or feature-level routing policy."""

    feature_label = serializers.CharField(source="get_feature_key_display", read_only=True)
    primary_model_id = serializers.PrimaryKeyRelatedField(
        source="primary_model",
        queryset=ModelConfig.objects.filter(is_active=True),
        allow_null=True,
        required=False,
    )
    backup_model_id = serializers.PrimaryKeyRelatedField(
        source="backup_model",
        queryset=ModelConfig.objects.filter(is_active=True),
        allow_null=True,
        required=False,
    )
    primary_model = SafeModelSummarySerializer(read_only=True)
    backup_model = SafeModelSummarySerializer(read_only=True)

    class Meta:
        model = ModelRoutingPolicy
        fields = (
            "id",
            "feature_key",
            "feature_label",
            "primary_model_id",
            "primary_model",
            "backup_model_id",
            "backup_model",
            "allow_fallback",
            "allow_deterministic_baseline",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "feature_label",
            "primary_model",
            "backup_model",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Reject inactive, incompatible, or duplicated primary/backup models."""
        feature_key = attrs.get(
            "feature_key",
            self.instance.feature_key if self.instance else ModelRoutingPolicy.FeatureKey.GLOBAL,
        )
        primary = attrs.get("primary_model", self.instance.primary_model if self.instance else None)
        backup = attrs.get("backup_model", self.instance.backup_model if self.instance else None)
        if primary and backup and primary.pk == backup.pk:
            raise serializers.ValidationError("主模型和备用模型不能是同一个配置。")
        if feature_key != ModelRoutingPolicy.FeatureKey.GLOBAL:
            required = set(required_model_types(feature_key))
            for field, model in (("primary_model_id", primary), ("backup_model_id", backup)):
                if model and model.model_type not in required:
                    raise serializers.ValidationError({field: "所选模型不支持该功能所需能力。"})
        return attrs

    def create(self, validated_data: dict[str, Any]) -> ModelRoutingPolicy:
        """Create a validated routing policy."""
        policy = ModelRoutingPolicy(**validated_data)
        policy.full_clean()
        policy.save()
        return policy

    def update(
        self,
        instance: ModelRoutingPolicy,
        validated_data: dict[str, Any],
    ) -> ModelRoutingPolicy:
        """Update one policy without touching model credentials."""
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.full_clean()
        instance.save()
        return instance


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
