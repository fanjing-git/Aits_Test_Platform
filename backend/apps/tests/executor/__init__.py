"""Executor primitives for the test execution domain."""

from apps.tests.executor.base import (
    BaseExecutor,
    ExecutionResult,
    ExecutorConfigurationError,
)

__all__ = ["BaseExecutor", "ExecutionResult", "ExecutorConfigurationError"]
