"""Embedding capability gates for production knowledge operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings

from apps.configs.models import ModelRoutingPolicy
from apps.configs.routing import ModelRouteCapabilityError, ModelRouteNotFound
from apps.knowledge.retrieval import HashVectorizer, Vectorizer
from core.llm.manager import ModelManager


class EmbeddingPolicyError(ValueError):
    """A safe, stable error raised when an embedding operation is gated."""

    def __init__(self, message: str, code: str, *, policy: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.policy = policy or {}


@dataclass(frozen=True)
class EmbeddingExecution:
    """Describe the explicitly selected embedding execution mode."""

    mode: str
    vectorizer: Vectorizer
    metadata: dict[str, Any]


class EmbeddingPolicyService:
    """Resolve embedding capability without silently treating HashVectorizer as production RAG."""

    PROVIDER = "provider"
    OFFLINE_TEST = "offline_test"
    MODES = (PROVIDER, OFFLINE_TEST)

    def __init__(self, model_manager: ModelManager | None = None) -> None:
        self.model_manager = model_manager or ModelManager()

    def describe(self) -> dict[str, Any]:
        """Return safe route and capability diagnostics for the knowledge workbench."""
        try:
            route = self.model_manager.resolve_route(
                ModelRoutingPolicy.FeatureKey.KNOWLEDGE_MODEL,
                task_type="embedding",
            )
        except ModelRouteCapabilityError as exc:
            return self._unavailable(
                getattr(exc, "code", "model_capability_mismatch"),
                str(exc),
            )
        except ModelRouteNotFound as exc:
            return self._unavailable("embedding_route_unavailable", str(exc))

        route_data = route.as_dict()
        if not route.available:
            return {
                **route_data,
                "available": False,
                "route_available": False,
                "provider_runtime": False,
                "code": "embedding_route_unavailable",
                "message": route.failure_reason,
                "route": route_data,
                "offline_test_available": bool(settings.DEBUG),
            }
        return {
            **route_data,
            "available": False,
            "route_available": True,
            "provider_runtime": False,
            "code": "embedding_provider_unavailable",
            "message": "已配置 Embedding 模型，但当前版本尚未接入供应商 Embedding 运行时；请使用后续 RAG 任务完成接入。",
            "route": route_data,
            "offline_test_available": bool(settings.DEBUG),
        }

    @staticmethod
    def _unavailable(code: str, message: str) -> dict[str, Any]:
        """Build a stable unavailable response without model credentials."""
        return {
            "feature_key": ModelRoutingPolicy.FeatureKey.KNOWLEDGE_MODEL,
            "required_model_types": ["embedding"],
            "available": False,
            "route_available": False,
            "provider_runtime": False,
            "code": code,
            "message": message,
            "route": {},
            "offline_test_available": bool(settings.DEBUG),
        }

    def prepare(self, mode: str = PROVIDER) -> EmbeddingExecution:
        """Prepare one explicit provider or offline-test embedding mode."""
        if mode not in self.MODES:
            raise EmbeddingPolicyError(
                "Embedding 执行模式无效。",
                "embedding_mode_invalid",
                policy=self.describe(),
            )
        if mode == self.OFFLINE_TEST:
            if not settings.DEBUG:
                raise EmbeddingPolicyError(
                    "生产环境禁止使用离线 HashVectorizer。",
                    "offline_embedding_disabled",
                    policy=self.describe(),
                )
            vectorizer = HashVectorizer()
            return EmbeddingExecution(
                mode=mode,
                vectorizer=vectorizer,
                metadata={
                    "embedding_mode": mode,
                    "embedding_provider": "local",
                    "embedding_model": vectorizer.model_name,
                    "embedding_dimensions": vectorizer.dimensions,
                },
            )

        policy = self.describe()
        raise EmbeddingPolicyError(str(policy["message"]), str(policy["code"]), policy=policy)
