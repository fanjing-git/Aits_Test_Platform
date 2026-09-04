"""Safe extension contracts for model configuration operations."""

from dataclasses import dataclass
from typing import Protocol

from apps.configs.models import ModelConfig


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    """Provider-neutral result returned by a connection adapter."""

    ok: bool
    message: str
    latency_ms: int | None = None


class ConnectionTester(Protocol):
    def test(self, config: ModelConfig) -> ConnectionTestResult: ...


class UnavailableConnectionTester:
    """Fail safely until a provider-specific adapter is explicitly registered."""

    def test(self, config: ModelConfig) -> ConnectionTestResult:
        return ConnectionTestResult(
            ok=False,
            message=f"No connection tester is registered for provider '{config.provider}'.",
        )
