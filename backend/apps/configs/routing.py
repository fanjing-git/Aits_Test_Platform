"""Deterministic model route resolution for platform and feature policies."""

from __future__ import annotations

from dataclasses import dataclass
from apps.configs.contracts import (
    ModelCallContract,
    ModelCapabilityError,
    model_call_contract,
    validate_model_capability,
)
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

    def as_dict(self) -> dict[str, object]:
        """Return safe route metadata without exposing credentials."""
        provider = getattr(self.config.provider, "value", self.config.provider)
        model_type = getattr(self.config.model_type, "value", self.config.model_type)
        return {
            "id": self.config.pk,
            "name": self.config.name,
            "provider": str(provider),
            "model_name": self.config.model_name,
            "model_type": str(model_type),
            "source": self.source,
            "is_fallback": self.is_fallback,
        }


@dataclass(frozen=True, slots=True)
class ResolvedModelRoute:
    """Resolved route metadata returned to model-consuming services."""

    feature_key: str
    required_types: tuple[str, ...]
    contract: ModelCallContract
    candidates: tuple[ModelRouteCandidate, ...]
    allow_fallback: bool = False
    allow_deterministic_baseline: bool = False

    @property
    def primary(self) -> ModelRouteCandidate | None:
        """Return the first candidate, if a model is available."""
        return self.candidates[0] if self.candidates else None

    @property
    def available(self) -> bool:
        """Whether the route contains a model that can execute the contract."""
        return bool(self.primary)

    @property
    def failure_reason(self) -> str:
        """Return a stable diagnostic when no model route is available."""
        if self.available:
            return ""
        return f"未配置支持{self.contract.label}的有效模型，请先配置功能路由或平台全局路由。"

    def as_dict(self) -> dict[str, object]:
        """Return JSON-safe route diagnostics for REST callers."""
        required_types = [getattr(item, "value", item) for item in self.required_types]
        return {
            "feature_key": self.feature_key,
            "required_model_types": [str(item) for item in required_types],
            "capability_contract": self.contract.as_dict(),
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "effective_source": self.primary.source if self.primary else "",
            "available": self.available,
            "allow_fallback": self.allow_fallback,
            "allow_deterministic_baseline": self.allow_deterministic_baseline,
            "failure_reason": self.failure_reason,
        }


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
    return model_call_contract(feature_key, task_type).accepted_model_types


def _require_compatible(config: ModelConfig, contract: ModelCallContract) -> None:
    """Validate a configured route against the complete call contract."""
    try:
        validate_model_capability(config, contract)
    except ModelCapabilityError as exc:
        raise ModelRouteCapabilityError(str(exc)) from exc


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
        contract = model_call_contract(normalized_feature, task_type)
        required = contract.accepted_model_types
        candidates: list[ModelRouteCandidate] = []

        if preferred_name:
            selected = ModelConfig.objects.filter(
                name=preferred_name,
                is_active=True,
            ).first()
            if selected is None:
                raise ModelRouteNotFound("本次选择的模型不存在或已停用。")
            _require_compatible(selected, contract)
            candidates.append(
                ModelRouteCandidate(selected, normalized_feature, "operation")
            )
            return ResolvedModelRoute(normalized_feature, required, contract, tuple(candidates))

        feature_policy = None
        if normalized_feature != ModelRoutingPolicy.FeatureKey.GLOBAL:
            feature_policy = ModelRoutingPolicy.objects.filter(
                feature_key=normalized_feature,
                is_active=True,
            ).select_related("primary_model", "backup_model").first()
            if feature_policy and feature_policy.primary_model_id:
                _require_compatible(feature_policy.primary_model, contract)
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
            _require_compatible(global_policy.primary_model, contract)
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
            _require_compatible(backup, contract)
            if all(candidate.config.pk != backup.pk for candidate in candidates):
                candidates.append(
                    ModelRouteCandidate(backup, normalized_feature, "backup", True)
                )
            allow_fallback = True
            allow_deterministic = bool(policy_for_backup.allow_deterministic_baseline)

        return ResolvedModelRoute(
            normalized_feature,
            required,
            contract,
            tuple(candidates),
            allow_fallback=allow_fallback,
            allow_deterministic_baseline=allow_deterministic,
        )
