"""Celery entry points for recoverable generation and review runs."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from core.task_state import TaskCancelled, task_runtime, utc_now
from apps.case_generation.generator import CaseGenerationError, generate_document_cases
from apps.case_generation.models import CaseGenerationRecord
from apps.case_generation.reviewer import CaseReviewError, review_generation_record
from apps.skills.business_execution import BusinessSkillRunService
from apps.skills.models import SkillChainRun


def _runtime(record: CaseGenerationRecord, task_id: str, report_name: str) -> dict[str, Any]:
    """Return the runtime for a generation or review report."""
    report = getattr(record, report_name, {})
    value = report.get("task_runtime") if isinstance(report, dict) else None
    if isinstance(value, dict) and value.get("task_id") == str(task_id):
        return dict(value)
    return task_runtime(str(task_id), "case_generation" if report_name == "coverage_report" else "case_review", status="running")


def _write(record: CaseGenerationRecord, report_name: str, runtime: Mapping[str, Any], *, rounds: list[dict[str, Any]] | None = None) -> None:
    """Persist runtime and round snapshots in the existing JSON report."""
    report = dict(getattr(record, report_name, {}) or {})
    report["task_runtime"] = dict(runtime)
    if rounds is not None:
        report["task_rounds"] = rounds
    setattr(record, report_name, report)
    record.save(update_fields=(report_name,))


def _callback(record_id: str, task_id: str, report_name: str):
    """Build a cooperative progress callback for a worker task."""
    def callback(update: Mapping[str, Any]) -> None:
        record = CaseGenerationRecord.objects.get(pk=record_id)
        runtime = _runtime(record, task_id, report_name)
        runtime.update({key: value for key, value in update.items() if key != "round"})
        runtime["updated_at"] = utc_now()
        rounds = list((getattr(record, report_name, {}) or {}).get("task_rounds") or [])
        round_item = update.get("round")
        if isinstance(round_item, Mapping):
            rounds = [item for item in rounds if item.get("round") != round_item.get("round")]
            rounds.append(dict(round_item))
            rounds.sort(key=lambda item: int(item.get("round", 0)))
        _write(record, report_name, runtime, rounds=rounds)
    return callback


def _cancel_check(record_id: str, task_id: str, report_name: str, business_run_id: str | None = None) -> bool:
    """Read the durable cancellation marker from the relevant report."""
    record = CaseGenerationRecord.objects.get(pk=record_id)
    runtime = _runtime(record, task_id, report_name)
    return runtime.get("cancel_requested") is True or bool(
        business_run_id and BusinessSkillRunService.cancel_requested(business_run_id)
    )


def _finish(record: CaseGenerationRecord, report_name: str, runtime: dict[str, Any], *, status: str, error_code: str = "") -> None:
    """Persist a terminal state and synchronize the record status."""
    runtime.update({"status": status, "error_code": error_code, "current_step": "已取消" if status == "cancelled" else ("已完成" if status == "completed" else "任务失败"), "updated_at": utc_now()})
    report = dict(getattr(record, report_name, {}) or {})
    report["task_runtime"] = runtime
    report["execution_status"] = status
    setattr(record, report_name, report)
    if status in {"failed", "cancelled", "timed_out"}:
        record.status = CaseGenerationRecord.Status.FAILED
    record.save(update_fields=(report_name, "status"))


@shared_task(
    bind=True,
    name="case_generation.run",
    soft_time_limit=25 * 60,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
)
def run_case_generation(
    self,
    record_id: str,
    preferred_model_name: str | None = None,
    task_id: str | None = None,
    business_run_id: str | None = None,
) -> dict[str, Any]:
    """Execute one queued five-round generation task."""
    del self
    task_id = str(task_id or uuid4().hex)
    record = CaseGenerationRecord.objects.get(pk=record_id)
    runtime = _runtime(record, task_id, "coverage_report")
    runtime.update({"status": "running", "current_step": "用例生成执行中", "updated_at": utc_now()})
    _write(record, "coverage_report", runtime)
    business_service = BusinessSkillRunService()
    business_run = None
    if business_run_id:
        business_run = business_service.mark_running(SkillChainRun.objects.get(pk=business_run_id), "case_generation")
    try:
        generated = generate_document_cases(
            record.document,
            preferred_model_name=preferred_model_name,
            record=record,
            progress_callback=_callback(str(record.pk), task_id, "coverage_report"),
            cancel_check=lambda: _cancel_check(str(record.pk), task_id, "coverage_report", business_run_id),
        )
        generated.refresh_from_db()
        _finish(generated, "coverage_report", _runtime(generated, task_id, "coverage_report"), status="completed")
        if business_run is not None:
            business_service.complete(
                business_run,
                "case_generation",
                {"record_id": str(generated.pk), "total_cases": generated.total_cases, "rounds": generated.rounds},
                artifact_ref={"type": "case_generation_record", "id": str(generated.pk)},
            )
        return {"status": "completed", "record_id": str(record.pk), "task_id": task_id}
    except TaskCancelled:
        record.refresh_from_db()
        _finish(record, "coverage_report", _runtime(record, task_id, "coverage_report"), status="cancelled")
        if business_run is not None:
            business_service.fail(business_run, "case_generation", "cancelled", "用例生成已取消，未产生可消费的完整用例集。")
        return {"status": "cancelled", "record_id": str(record.pk), "task_id": task_id}
    except SoftTimeLimitExceeded:
        record.refresh_from_db()
        _finish(record, "coverage_report", _runtime(record, task_id, "coverage_report"), status="timed_out", error_code="task_timeout")
        if business_run is not None:
            business_service.fail(business_run, "case_generation", "task_timeout", "用例生成任务超时。")
        return {"status": "timed_out", "record_id": str(record.pk), "task_id": task_id}
    except CaseGenerationError as exc:
        record.refresh_from_db()
        _finish(record, "coverage_report", _runtime(record, task_id, "coverage_report"), status="failed", error_code="generation_failed")
        if business_run is not None:
            business_service.fail(business_run, "case_generation", "generation_failed", str(exc))
        return {"status": "failed", "record_id": str(record.pk), "task_id": task_id, "error_code": "generation_failed", "detail": str(exc)[:200]}
    except Exception:
        record.refresh_from_db()
        _finish(record, "coverage_report", _runtime(record, task_id, "coverage_report"), status="failed", error_code="task_error")
        if business_run is not None:
            business_service.fail(business_run, "case_generation", "task_error", "用例生成任务失败。")
        return {"status": "failed", "record_id": str(record.pk), "task_id": task_id, "error_code": "task_error"}


@shared_task(
    bind=True,
    name="case_generation.review",
    soft_time_limit=25 * 60,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
)
def run_case_review(
    self,
    record_id: str,
    preferred_model_name: str | None = None,
    task_id: str | None = None,
    business_run_id: str | None = None,
) -> dict[str, Any]:
    """Execute one queued five-round review task."""
    del self
    task_id = str(task_id or uuid4().hex)
    record = CaseGenerationRecord.objects.get(pk=record_id)
    runtime = _runtime(record, task_id, "review_report")
    runtime.update({"status": "running", "current_step": "用例评审执行中", "updated_at": utc_now()})
    record.status = CaseGenerationRecord.Status.REVIEWING
    record.save(update_fields=("status",))
    _write(record, "review_report", runtime)
    business_service = BusinessSkillRunService()
    business_run = None
    if business_run_id:
        business_run = business_service.mark_running(SkillChainRun.objects.get(pk=business_run_id), "case_review")
    try:
        reviewed = review_generation_record(
            record,
            preferred_model_name=preferred_model_name,
            progress_callback=_callback(str(record.pk), task_id, "review_report"),
            cancel_check=lambda: _cancel_check(str(record.pk), task_id, "review_report", business_run_id),
        )
        reviewed.refresh_from_db()
        _finish(reviewed, "review_report", _runtime(reviewed, task_id, "review_report"), status="completed")
        if business_run is not None:
            business_service.complete(
                business_run,
                "case_review",
                {"record_id": str(reviewed.pk), "review_rounds": reviewed.review_rounds, "issue_count": len((reviewed.review_report or {}).get("issues", []))},
                artifact_ref={"type": "case_review", "id": str(reviewed.pk)},
            )
        return {"status": "completed", "record_id": str(record.pk), "task_id": task_id}
    except TaskCancelled:
        record.refresh_from_db()
        _finish(record, "review_report", _runtime(record, task_id, "review_report"), status="cancelled")
        if business_run is not None:
            business_service.fail(business_run, "case_review", "cancelled", "用例评审已取消。")
        return {"status": "cancelled", "record_id": str(record.pk), "task_id": task_id}
    except SoftTimeLimitExceeded:
        record.refresh_from_db()
        _finish(record, "review_report", _runtime(record, task_id, "review_report"), status="timed_out", error_code="task_timeout")
        if business_run is not None:
            business_service.fail(business_run, "case_review", "task_timeout", "用例评审任务超时。")
        return {"status": "timed_out", "record_id": str(record.pk), "task_id": task_id}
    except CaseReviewError as exc:
        record.refresh_from_db()
        _finish(record, "review_report", _runtime(record, task_id, "review_report"), status="failed", error_code="review_failed")
        if business_run is not None:
            business_service.fail(business_run, "case_review", "review_failed", str(exc))
        return {"status": "failed", "record_id": str(record.pk), "task_id": task_id, "error_code": "review_failed", "detail": str(exc)[:200]}
    except Exception:
        record.refresh_from_db()
        _finish(record, "review_report", _runtime(record, task_id, "review_report"), status="failed", error_code="task_error")
        if business_run is not None:
            business_service.fail(business_run, "case_review", "task_error", "用例评审任务失败。")
        return {"status": "failed", "record_id": str(record.pk), "task_id": task_id, "error_code": "task_error"}


__all__ = ["run_case_generation", "run_case_review"]
