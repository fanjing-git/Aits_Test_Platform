"""Business services for creating and executing persisted test runs."""

from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.tests.executor.api_executor import APIExecutor
from apps.tests.executor.base import ExecutionResult
from apps.tests.models import TestResult, TestRun


def create_test_run(*, project: Any, user: Any, name: str, mode: str, environment: Any, cases: list[Any], execution_config: dict[str, Any] | None = None) -> TestRun:
    """Create a pending run and attach only cases already validated for its project."""
    with transaction.atomic():
        run = TestRun(
            project=project,
            environment=environment,
            name=name,
            mode=mode,
            created_by=user,
            execution_config=execution_config or {},
        )
        run.full_clean()
        run.save()
        run.attach_test_cases(*cases)
    return run


def _persist_execution_result(run: TestRun, result: ExecutionResult) -> TestRun:
    """Persist redacted executor output and aggregate status in one transaction."""
    now = timezone.now()
    details = result.details if isinstance(result.details, list) else []
    cases = {case.case_id: case for case in run.test_cases.all()}
    with transaction.atomic():
        for item in details:
            if not isinstance(item, dict) or item.get("case_id") not in cases:
                continue
            TestResult.objects.update_or_create(
                run=run,
                test_case=cases[item["case_id"]],
                defaults={
                    "status": item.get("status", TestResult.Status.ERROR),
                    "duration_ms": item.get("duration_ms"),
                    "status_code": item.get("status_code"),
                    "response_summary": item.get("response_summary") if isinstance(item.get("response_summary"), dict) else {},
                    "assertions": item.get("assertions") if isinstance(item.get("assertions"), list) else [],
                    "error_code": str(item.get("error_code") or "")[:80],
                    "error_message": str(item.get("error_message") or ""),
                    "started_at": run.started_at or now,
                    "completed_at": now,
                },
            )
        status = TestRun.Status.COMPLETED if result.status in {"passed", "skipped"} else TestRun.Status.FAILED
        run.status = status
        run.completed_at = now
        run.summary = {
            "status": result.status,
            "passed": result.passed,
            "failed": result.failed,
            "skipped": result.skipped,
            "errors": result.errors,
            "duration_ms": result.duration_ms,
            "error_code": result.error_code,
            "error_message": result.error_message,
        }
        run.save(update_fields=["status", "completed_at", "summary"])
    return run


def execute_test_run(run: TestRun) -> TestRun:
    """Execute a pending run through its concrete executor and persist safe results."""
    run.status = TestRun.Status.RUNNING
    run.started_at = timezone.now()
    run.completed_at = None
    run.save(update_fields=["status", "started_at", "completed_at"])
    try:
        result = APIExecutor(run).execute()
    except Exception:
        result = ExecutionResult(
            status="error", exit_code=None, error_code="executor_unavailable", error_message="测试执行器暂时不可用。"
        )
    return _persist_execution_result(run, result)
