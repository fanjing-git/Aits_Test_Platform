"""Shared state and cancellation primitives for long-running workbench tasks."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping


class TaskCancelled(Exception):
    """Raised when a user cancellation request is observed by a worker."""


ProgressCallback = Callable[[Mapping[str, Any]], None]
CancelCheck = Callable[[], bool]


def utc_now() -> str:
    """Return a stable, timezone-aware timestamp for task diagnostics."""
    return datetime.now(timezone.utc).isoformat()


def task_runtime(
    task_id: str,
    task_type: str,
    *,
    status: str = "pending",
    current_step: str = "排队中",
    current_round: int = 0,
    total_rounds: int = 5,
    completed_rounds: int = 0,
    retryable: bool = True,
    error_code: str = "",
    cancel_requested: bool = False,
    result_id: str = "",
) -> dict[str, Any]:
    """Build the credential-free runtime payload stored in existing JSON fields."""
    return {
        "task_id": str(task_id),
        "task_type": task_type,
        "status": status,
        "current_step": current_step,
        "current_round": current_round,
        "total_rounds": total_rounds,
        "completed_rounds": completed_rounds,
        "retryable": retryable,
        "error_code": error_code,
        "cancel_requested": cancel_requested,
        "result_id": result_id,
        "updated_at": utc_now(),
    }


def ensure_not_cancelled(cancel_check: CancelCheck | None) -> None:
    """Raise a cooperative cancellation exception when the user requested it."""
    if cancel_check and cancel_check():
        raise TaskCancelled("任务已按用户请求取消。")


__all__ = ["CancelCheck", "ProgressCallback", "TaskCancelled", "ensure_not_cancelled", "task_runtime", "utc_now"]
