"""Deterministic model route resolution for platform and feature policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from apps.configs.models import ModelConfig, ModelRoutingPolicy


class ModelRouteError(RuntimeError):
    """Base error for safe route resolution failures."""


class ModelRouteNotFound(ModelRouteError):
    """Raised when no compatible model is available for a feature."""


class ModelRouteCapabilityError(ModelRouteError):
    """Raised when an explicit route points to an incompatible model."""


@dataclass(frozen=True, slots=True)
class ModelRouteCandidate:
    """One model candidate and the policy source that selected it."""

    config: ModelConfig
    feature_key: str
    source: str
    is_fallback: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedModelRoute:
    """Resolved route metadata returned to model-consuming services."""

    feature_key: str
    required_types: tuple[str, ...]
    candidates: tuple[ModelRouteCandidate, ...]
    allow_fallback: bool = False
    allow_deterministic_baseline: bool = False

    @property
    def primary(self) -> ModelRouteCandidate | None:
        """Return the first candidate, if a model is available."""
        return self.candidates[0] if self.candidates else None


FEATURE_ALIASES = {
    "requirement": ModelRoutingPolicy.FeatureKey.REQUIREMENT_ANALYSIS,
    "requirement_analysis": ModelRoutingPolicy.FeatureKey.REQUIREMENT_ANALYSIS,
    "case_gen": ModelRoutingPolicy.FeatureKey.CASE_GENERATION,
    "case_generation": ModelRoutingPolicy.FeatureKey.CASE_GENERATION,
    "case_review": ModelRoutingPolicy.FeatureKey.CASE_REVIEW,
    "screenshot": ModelRoutingPolicy.FeatureKey.SCREENSHOT_ANALYSIS,
    "vision": ModelRoutingPolicy.FeatureKey.SCREENSHOT_ANALYSIS,
    "agent": ModelRoutingPolicy.FeatureKey.AGENT_EXECUTION,
    "agent_execution": ModelRoutingPolicy.FeatureKey.AGENT_EXECUTION,
    "report": ModelRoutingPolicy.FeatureKey.REPORT_GENERATION,
    "report_generation": ModelRoutingPolicy.FeatureKey.REPORT_GENERATION,
    "knowledge": ModelRoutingPolicy.FeatureKey.KNOWLEDGE_MODEL,
    "knowledge_model": ModelRoutingPolicy.FeatureKey.KNOWLEDGE_MODEL,
}

TEXT_TYPES = (
    ModelConfig.ModelType.CHAT,
    ModelConfig.ModelType.MULTIMODAL,
    ModelConfig.ModelType.VISION,
)


def normalize_feature_key(feature_key: str | None) -> str:
    """Normalize a public feature alias to the persisted route key."""
    value = (feature_key or ModelRoutingPolicy.FeatureKey.GLOBAL).strip().lower()
    return str(FEATURE_ALIASES.get(value, value))


def required_model_types(
    feature_key: str | None,
    task_type: str | None = None,
) -> tuple[str, ...]:
    """Return the model capabilities a feature is allowed to use."""
    task = (task_type or "").strip().lower().replace("-", "_")
    if task in {ModelConfig.ModelType.EMBEDDING, "embedding", "vectorization", "indexing", "retrieval"}:
        return (ModelConfig.ModelType.EMBEDDING,)
    if task in {"vision", "screenshot", "image_analysis"}:
        return (ModelConfig.ModelType.VISION, ModelConfig.ModelType.MULTIMODAL)
    if task in {"audio", "tts", "asr", "realtime", "rerank"}:
        return (task,)
    feature = normalize_feature_key(feature_key)
    if feature == ModelRoutingPolicy.FeatureKey.SCREENSHOT_ANALYSIS:
        return (ModelConfig.ModelType.VISION, ModelConfig.ModelType.MULTIMODAL)
    if feature == ModelRoutingPolicy.FeatureKey.GLOBAL and not task:
        return tuple(choice.value for choice in ModelConfig.ModelType)
    if feature == ModelRoutingPolicy.FeatureKey.KNOWLEDGE_MODEL:
        return (ModelConfig.ModelType.EMBEDDING, ModelConfig.ModelType.RERANK)
    if feature in {
        ModelRoutingPolicy.FeatureKey.REQUIREMENT_ANALYSIS,
        ModelRoutingPolicy.FeatureKey.CASE_GENERATION,
        ModelRoutingPolicy.FeatureKey.CASE_REVIEW,
        ModelRoutingPolicy.FeatureKey.AGENT_EXECUTION,
        ModelRoutingPolicy.FeatureKey.REPORT_GENERATION,
    }:
        return TEXT_TYPES
    if task in {choice.value for choice in ModelConfig.ModelType}:
        return (task,)
    return (ModelConfig.ModelType.CHAT,)


def _compatible(config: ModelConfig | None, required: Iterable[str]) -> bool:
    """Check active status and capability compatibility without touching secrets."""
    return bool(config and config.is_active and config.model_type in set(required))


class ModelRouteResolver:
    """Resolve routes with explicit precedence and no implicit fallback."""

    def resolve(
        self,
        feature_key: str | None,
        *,
        task_type: str | None = None,
        preferred_name: str | None = None,
        baseline_requested: bool = False,
    ) -> ResolvedModelRoute:
        """Resolve temporary, feature, global, and legacy model choices."""
        normalized_feature = normalize_feature_key(feature_key)
        required = required_model_types(normalized_feature, task_type)
        candidates: list[ModelRouteCandidate] = []

        if preferred_name:
            selected = ModelConfig.objects.filter(
                name=preferred_name,
                is_active=True,
            ).first()
            if selected is None:
                raise ModelRouteNotFound("本次选择的模型不存在或已停用。")
            if not _compatible(selected, required):
                raise ModelRouteCapabilityError("本次选择的模型不支持该功能所需能力。")
            candidates.append(
                ModelRouteCandidate(selected, normalized_feature, "operation")
            )
            return ResolvedModelRoute(normalized_feature, required, tuple(candidates))

        feature_policy = None
        if normalized_feature != ModelRoutingPolicy.FeatureKey.GLOBAL:
            feature_policy = ModelRoutingPolicy.objects.filter(
                feature_key=normalized_feature,
                is_active=True,
            ).select_related("primary_model", "backup_model").first()
            if feature_policy and feature_policy.primary_model_id:
                if not _compatible(feature_policy.primary_model, required):
                    raise ModelRouteCapabilityError("功能绑定模型不支持该功能所需能力。")
                candidates.append(
                    ModelRouteCandidate(
                        feature_policy.primary_model,
                        normalized_feature,
                        "feature",
                    )
                )

        global_policy = ModelRoutingPolicy.objects.filter(
            feature_key=ModelRoutingPolicy.FeatureKey.GLOBAL,
            is_active=True,
        ).select_related("primary_model", "backup_model").first()
        if global_policy and global_policy.primary_model_id and not candidates:
            if not _compatible(global_policy.primary_model, required):
                raise ModelRouteCapabilityError("平台全局模型不支持该功能所需能力，请选择兼容模型。")
            if not candidates:
                candidates.append(
                    ModelRouteCandidate(global_policy.primary_model, normalized_feature, "global")
                )

        if not candidates:
            legacy = ModelConfig.objects.filter(
                is_active=True,
                is_default=True,
                model_type__in=required,
            ).order_by("priority", "name").first()
            if legacy:
                candidates.append(
                    ModelRouteCandidate(legacy, normalized_feature, "legacy_type_default")
                )

        allow_fallback = bool(feature_policy and feature_policy.allow_fallback)
        allow_deterministic = bool(
            feature_policy and feature_policy.allow_deterministic_baseline
        )
        policy_for_backup = feature_policy or global_policy
        if policy_for_backup and policy_for_backup.allow_fallback and policy_for_backup.backup_model_id:
            backup = policy_for_backup.backup_model
            if not _compatible(backup, required):
                raise ModelRouteCapabilityError("已启用的备用模型不支持该功能所需能力。")
            if all(candidate.config.pk != backup.pk for candidate in candidates):
                candidates.append(
                    ModelRouteCandidate(backup, normalized_feature, "backup", True)
                )
            allow_fallback = True
            allow_deterministic = bool(policy_for_backup.allow_deterministic_baseline)

        return ResolvedModelRoute(
            normalized_feature,
            required,
            tuple(candidates),
            allow_fallback=allow_fallback,
            allow_deterministic_baseline=allow_deterministic,
        )
