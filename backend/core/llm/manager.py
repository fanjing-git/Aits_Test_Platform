"""Configuration-driven model loading, routing, switching, and fallback."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import time
from typing import Any, Protocol, TypeVar

from apps.configs.contracts import model_call_contract
from apps.configs.models import ModelConfig
from apps.configs.observability import ModelCallObservability
from apps.configs.routing import ModelRouteResolver, ResolvedModelRoute

ModelT = TypeVar("ModelT")
ResultT = TypeVar("ResultT")


class ModelFactory(Protocol[ModelT]):
    """Minimal contract implemented by the provider factory in later tasks."""

    def __call__(self, config: ModelConfig) -> ModelT: ...


class ModelManagerError(RuntimeError):
    """Base error for safe model-management failures."""


class ModelNotFound(ModelManagerError):
    """Raised when no active configuration satisfies a route."""


class ModelFactoryNotConfigured(ModelManagerError):
    """Raised when a runtime instance is requested without a factory."""


class ModelFallbackExhausted(ModelManagerError):
    """Raised after every eligible model failed an operation."""

    def __init__(
        self,
        attempted_models: Iterable[str],
        *,
        last_error: Exception | None = None,
    ) -> None:
        self.attempted_models = tuple(attempted_models)
        self.last_error = last_error
        attempted = ", ".join(self.attempted_models) or "none"
        super().__init__(f"All eligible models failed. Attempted: {attempted}")


class ModelManager:
    """Resolve active model configurations and isolate provider construction."""

    TEXT_ANALYSIS_TYPES = frozenset({
        ModelConfig.ModelType.CHAT,
        ModelConfig.ModelType.MULTIMODAL,
        ModelConfig.ModelType.VISION,
    })

    TASK_MODEL_TYPES = {
        "embedding": ModelConfig.ModelType.EMBEDDING,
        "vectorization": ModelConfig.ModelType.EMBEDDING,
        "indexing": ModelConfig.ModelType.EMBEDDING,
        "retrieval": ModelConfig.ModelType.EMBEDDING,
        "vision": ModelConfig.ModelType.VISION,
        "image": ModelConfig.ModelType.VISION,
        "screenshot": ModelConfig.ModelType.VISION,
        "ocr": ModelConfig.ModelType.VISION,
    }

    def __init__(self, factory: ModelFactory[Any] | None = None) -> None:
        self._factory = factory
        self._route_resolver = ModelRouteResolver()
        self._configs: tuple[ModelConfig, ...] = ()
        self._selected_names: dict[str, str] = {}
        self._instances: dict[int, Any] = {}
        self.load()

    def resolve_route(
        self,
        feature_key: str,
        *,
        task_type: str | None = None,
        preferred_name: str | None = None,
        baseline_requested: bool = False,
    ) -> ResolvedModelRoute:
        """Resolve the new platform/function route without changing legacy APIs."""
        return self._route_resolver.resolve(
            feature_key,
            task_type=task_type,
            preferred_name=preferred_name,
            baseline_requested=baseline_requested,
        )

    def execute_routed(
        self,
        feature_key: str,
        operation: Callable[[Any, ModelConfig], ResultT],
        *,
        task_type: str | None = None,
        preferred_name: str | None = None,
        baseline_requested: bool = False,
        retry_on: tuple[type[Exception], ...] = (Exception,),
        request_id: str | None = None,
    ) -> ResultT:
        """Execute a new route and only use a policy-enabled backup model."""
        correlation_id = request_id or ModelCallObservability.new_request_id()
        try:
            route = self.resolve_route(
                feature_key,
                task_type=task_type,
                preferred_name=preferred_name,
                baseline_requested=baseline_requested,
            )
        except Exception as exc:
            ModelCallObservability.blocked(
                feature_key=str(feature_key),
                task_type=task_type,
                request_id=correlation_id,
                error_code=getattr(exc, "code", exc.__class__.__name__),
                failure_stage="route_resolution",
            )
            raise
        if not route.candidates:
            ModelCallObservability.blocked(
                feature_key=route.feature_key,
                task_type=task_type,
                request_id=correlation_id,
                error_code="route_unavailable",
                failure_stage="route_resolution",
                trace=[{"feature_key": route.feature_key, "available": route.available}],
            )
            if route.allow_deterministic_baseline and baseline_requested:
                raise ModelNotFound("已选择确定性基线，但该执行器没有模型运行时。")
            raise ModelNotFound("未配置支持该功能的模型，请先配置全局或功能模型。")

        attempted: list[str] = []
        last_error: Exception | None = None
        for index, candidate in enumerate(route.candidates):
            if index > 0 and (not route.allow_fallback or not candidate.is_fallback):
                break
            attempted.append(candidate.config.name)
            started = time.perf_counter()
            record = ModelCallObservability.start(
                feature_key=route.feature_key,
                task_type=task_type,
                config=candidate.config,
                route_source=candidate.source,
                is_fallback=candidate.is_fallback,
                request_id=correlation_id,
            )
            try:
                result = operation(self._get_or_create(candidate.config), candidate.config)
                ModelCallObservability.complete(
                    record,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
                return result
            except retry_on as exc:
                ModelCallObservability.fail(
                    record,
                    exc,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
                last_error = exc
        raise ModelFallbackExhausted(attempted, last_error=last_error) from last_error

    def load(self) -> tuple[ModelConfig, ...]:
        """Reload active configurations in deterministic fallback order."""
        self._configs = tuple(
            ModelConfig.objects.filter(is_active=True).order_by(
                "model_type", "-is_default", "priority", "name"
            )
        )
        active_names = {config.name for config in self._configs}
        self._selected_names = {
            model_type: name
            for model_type, name in self._selected_names.items()
            if name in active_names
        }
        self._instances = {
            config_id: instance
            for config_id, instance in self._instances.items()
            if any(config.pk == config_id for config in self._configs)
        }
        return self._configs

    @classmethod
    def resolve_model_type(cls, task_type: str | None) -> str:
        """Map a task label to the capability required from a model."""
        contract = model_call_contract(task_type or "chat", task_type=task_type)
        return contract.accepted_model_types[0]

    def candidates(
        self,
        task_type: str | None = None,
        *,
        preferred_name: str | None = None,
    ) -> tuple[ModelConfig, ...]:
        """Return eligible configurations, placing an explicit choice first."""
        contract = model_call_contract(task_type or "chat", task_type=task_type)
        model_type = contract.accepted_model_types[0]
        eligible = [c for c in self._configs if c.model_type in contract.accepted_model_types]
        if len(contract.accepted_model_types) > 1:
            eligible.sort(key=lambda config: (-int(config.is_default), config.priority, config.model_type, config.name))
        selected_name = preferred_name or self._selected_names.get(model_type)
        if not preferred_name and len(contract.accepted_model_types) > 1 and not selected_name:
            selected_name = next(
                (self._selected_names.get(candidate_type) for candidate_type in contract.accepted_model_types if self._selected_names.get(candidate_type)),
                None,
            )
        if selected_name:
            selected = next((c for c in eligible if c.name == selected_name), None)
            if selected is None:
                raise ModelNotFound(
                    f"Active model '{selected_name}' does not support '{model_type}'."
                )
            eligible.remove(selected)
            eligible.insert(0, selected)
        return tuple(eligible)

    def get_config(
        self,
        task_type: str | None = None,
        *,
        preferred_name: str | None = None,
    ) -> ModelConfig:
        """Get the highest-ranked active configuration for a task."""
        candidates = self.candidates(task_type, preferred_name=preferred_name)
        if not candidates:
            model_type = self.resolve_model_type(task_type)
            raise ModelNotFound(f"No active model is configured for '{model_type}'.")
        return candidates[0]

    def switch(self, model_name: str) -> ModelConfig:
        """Select an active model for subsequent tasks of the same capability."""
        config = next((c for c in self._configs if c.name == model_name), None)
        if config is None:
            raise ModelNotFound(f"Active model '{model_name}' was not found.")
        self._selected_names[config.model_type] = config.name
        return config

    def get_model(
        self,
        task_type: str | None = None,
        *,
        preferred_name: str | None = None,
    ) -> Any:
        """Create once and return the runtime instance for a routed config."""
        return self._get_or_create(self.get_config(task_type, preferred_name=preferred_name))

    def execute_with_fallback(
        self,
        task_type: str | None,
        operation: Callable[[Any, ModelConfig], ResultT],
        *,
        preferred_name: str | None = None,
        retry_on: tuple[type[Exception], ...] = (Exception,),
        request_id: str | None = None,
    ) -> ResultT:
        """Try eligible models in order and return the first successful result."""
        correlation_id = request_id or ModelCallObservability.new_request_id()
        attempted: list[str] = []
        last_error: Exception | None = None
        try:
            configs = self.candidates(task_type, preferred_name=preferred_name)
        except Exception as exc:
            ModelCallObservability.blocked(
                feature_key=str(task_type or "chat"),
                task_type=task_type,
                request_id=correlation_id,
                error_code=getattr(exc, "code", exc.__class__.__name__),
                failure_stage="route_resolution",
            )
            raise
        if not configs:
            ModelCallObservability.blocked(
                feature_key=str(task_type or "chat"),
                task_type=task_type,
                request_id=correlation_id,
                error_code="route_unavailable",
                failure_stage="route_resolution",
            )
            raise ModelNotFound(
                f"No active model is configured for '{self.resolve_model_type(task_type)}'."
            )

        for config in configs:
            attempted.append(config.name)
            started = time.perf_counter()
            record = ModelCallObservability.start(
                feature_key=str(task_type or "chat"),
                task_type=task_type,
                config=config,
                route_source="legacy_fallback",
                is_fallback=bool(attempted[:-1]),
                request_id=correlation_id,
            )
            try:
                result = operation(self._get_or_create(config), config)
                ModelCallObservability.complete(
                    record,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
                return result
            except retry_on as exc:
                ModelCallObservability.fail(
                    record,
                    exc,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
                last_error = exc

        raise ModelFallbackExhausted(attempted, last_error=last_error) from last_error

    def _get_or_create(self, config: ModelConfig) -> Any:
        if self._factory is None:
            raise ModelFactoryNotConfigured(
                "A model factory is required to create runtime instances."
            )
        if config.pk not in self._instances:
            self._instances[config.pk] = self._factory(config)
        return self._instances[config.pk]
