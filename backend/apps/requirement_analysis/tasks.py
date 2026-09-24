"""Celery entry points for recoverable requirement-analysis runs."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from core.task_state import TaskCancelled, task_runtime, utc_now
from apps.requirement_analysis.analyzer import RequirementAnalysisError, analyze_requirement_document
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument
from apps.requirement_analysis.services import RequirementAnalysisConfirmationError, RequirementAnalysisRecordService
from apps.skills.business_execution import BusinessSkillRunService
from apps.skills.models import SkillChainRun


TASK_TYPE = "requirement_analysis"


def set_requirement_runtime(document: RequirementDocument, runtime: Mapping[str, Any], *, status: str | None = None) -> None:
    """Persist task state in the existing document baseline JSON without storing secrets."""
    baseline = dict(document.analysis_baseline or {})
    baseline["_task_runtime"] = dict(runtime)
    document.analysis_baseline = baseline
    fields = ["analysis_baseline"]
    if status:
        document.status = status
        fields.append("status")
    document.save(update_fields=fields)


def _runtime(document: RequirementDocument, task_id: str) -> dict[str, Any]:
    """Return the current task runtime or initialize it for a worker retry."""
    value = (document.analysis_baseline or {}).get("_task_runtime")
    if isinstance(value, dict) and value.get("task_id") == str(task_id):
        return dict(value)
    return task_runtime(str(task_id), TASK_TYPE, status="running", current_step="开始需求分析")


def _progress_callback(document_id: str, task_id: str):
    """Build a callback that atomically records round progress."""
    def callback(update: Mapping[str, Any]) -> None:
        document = RequirementDocument.objects.get(pk=document_id)
        runtime = _runtime(document, task_id)
        runtime.update({key: value for key, value in update.items() if key != "round"})
        runtime["updated_at"] = utc_now()
        rounds = list((document.analysis_baseline or {}).get("_task_rounds") or [])
        round_item = update.get("round")
        if isinstance(round_item, Mapping):
            rounds = [item for item in rounds if item.get("round") != round_item.get("round")]
            rounds.append(dict(round_item))
            rounds.sort(key=lambda item: int(item.get("round", 0)))
        baseline = dict(document.analysis_baseline or {})
        baseline["_task_runtime"] = runtime
        baseline["_task_rounds"] = rounds
        document.analysis_baseline = baseline
        document.save(update_fields=("analysis_baseline",))
    return callback


def _cancel_check(document_id: str, task_id: str, business_run_id: str | None = None) -> bool:
    """Read the durable cancellation marker written by the REST endpoint."""
    document = RequirementDocument.objects.get(pk=document_id)
    runtime = (document.analysis_baseline or {}).get("_task_runtime") or {}
    document_cancelled = runtime.get("task_id") == str(task_id) and bool(runtime.get("cancel_requested"))
    return document_cancelled or bool(business_run_id and BusinessSkillRunService.cancel_requested(business_run_id))


def _finish(document: RequirementDocument, runtime: dict[str, Any], *, status: str, result_id: str = "", error_code: str = "") -> None:
    """Persist a terminal runtime and remove the transient document marker."""
    runtime.update({"status": status, "result_id": result_id, "error_code": error_code, "current_step": "已取消" if status == "cancelled" else ("已完成" if status == "completed" else "任务失败"), "updated_at": utc_now()})
    baseline = dict(document.analysis_baseline or {})
    baseline.pop("_task_runtime", None)
    rounds = baseline.pop("_task_rounds", [])
    baseline["_last_task_runtime"] = {**runtime, "rounds": rounds}
    document.analysis_baseline = baseline
    if status == "completed":
        document.status = RequirementDocument.Status.ANALYZED
    elif status == "cancelled":
        has_previous_analysis = document.analyses.exclude(quality_status=RequirementAnalysis.QualityStatus.FAILED).exists()
        document.status = RequirementDocument.Status.ANALYZED if has_previous_analysis else RequirementDocument.Status.UPLOADED
    else:
        document.status = RequirementDocument.Status.FAILED
    document.save(update_fields=("analysis_baseline", "status"))
    if result_id:
        analysis = RequirementAnalysis.objects.filter(pk=result_id).first()
        if analysis:
            report = dict(analysis.coverage_report or {})
            report["task_runtime"] = {**runtime, "rounds": rounds}
            analysis.coverage_report = report
            analysis.save(update_fields=("coverage_report",))


@shared_task(
    bind=True,
    name="requirement_analysis.run",
    soft_time_limit=25 * 60,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
)
def run_requirement_analysis(
    self,
    document_id: str,
    preferred_model_name: str | None = None,
    resume_from_round: int = 1,
    task_id: str | None = None,
    business_run_id: str | None = None,
) -> dict[str, Any]:
    """Execute one recoverable requirement-analysis task in a worker."""
    del self
    task_id = str(task_id or uuid4().hex)
    document = RequirementDocument.objects.get(pk=document_id)
    runtime = _runtime(document, task_id)
    runtime.update({"status": "running", "current_step": "需求分析执行中", "updated_at": utc_now()})
    set_requirement_runtime(document, runtime, status=RequirementDocument.Status.ANALYZING)
    business_service = BusinessSkillRunService()
    business_run = None
    if business_run_id:
        business_run = business_service.mark_running(
            SkillChainRun.objects.get(pk=business_run_id),
            "requirement_analysis",
        )
    try:
        analysis = analyze_requirement_document(
            document,
            preferred_model_name=preferred_model_name,
            resume_from_round=int(resume_from_round),
            progress_callback=_progress_callback(str(document.pk), task_id),
            cancel_check=lambda: _cancel_check(str(document.pk), task_id, business_run_id),
        )
        document.refresh_from_db()
        runtime = _runtime(document, task_id)
        if runtime.get("cancel_requested"):
            raise TaskCancelled("任务已按用户请求取消。")
        _finish(document, runtime, status="completed", result_id=str(analysis.pk))
        if business_run is not None:
            business_service.complete(
                business_run,
                "requirement_analysis",
                {
                    "analysis_id": str(analysis.pk),
                    "quality_status": analysis.quality_status,
                    "module_count": len(analysis.modules or []),
                    "function_count": len(analysis.functions or []),
                    "test_point_count": len(analysis.test_points or []),
                },
                artifact_ref={"type": "requirement_analysis", "id": str(analysis.pk)},
            )
        return {"status": "completed", "result_id": str(analysis.pk), "task_id": task_id}
    except TaskCancelled:
        document.refresh_from_db()
        _finish(document, _runtime(document, task_id), status="cancelled")
        if business_run is not None:
            business_service.fail(business_run, "requirement_analysis", "cancelled", "需求分析已取消，未产生可消费的完整分析结果。")
        return {"status": "cancelled", "task_id": task_id}
    except SoftTimeLimitExceeded:
        document.refresh_from_db()
        _finish(document, _runtime(document, task_id), status="timed_out", error_code="task_timeout")
        if business_run is not None:
            business_service.fail(business_run, "requirement_analysis", "task_timeout", "需求分析任务超时。")
        return {"status": "timed_out", "task_id": task_id}
    except RequirementAnalysisError as exc:
        document.refresh_from_db()
        latest = document.analyses.order_by("-created_at").first()
        runtime = _runtime(document, task_id)
        runtime.update({"error_code": exc.code, "retryable": exc.retryable})
        if latest:
            report = dict(latest.coverage_report or {})
            report["task_runtime"] = runtime
            latest.coverage_report = report
            latest.save(update_fields=("coverage_report",))
        _finish(document, runtime, status="failed", result_id=str(latest.pk) if latest else "", error_code=exc.code)
        if business_run is not None:
            business_service.fail(business_run, "requirement_analysis", exc.code, str(exc))
        return {"status": "failed", "task_id": task_id, "error_code": exc.code}
    except Exception:
        document.refresh_from_db()
        _finish(document, _runtime(document, task_id), status="failed", error_code="task_error")
        if business_run is not None:
            business_service.fail(business_run, "requirement_analysis", "task_error", "需求分析任务失败。")
        return {"status": "failed", "task_id": task_id, "error_code": "task_error"}


@shared_task(bind=True, name="requirement_analysis.review", max_retries=2)
def run_requirement_review(self, document_id: str, business_run_id: str) -> dict[str, Any]:
    """Execute the same requirement-review Service used by the synchronous API."""
    del self
    service = BusinessSkillRunService()
    run = SkillChainRun.objects.get(pk=business_run_id)
    try:
        service.mark_running(run, "requirement_review")
        analysis = RequirementAnalysisRecordService().review_latest_analysis(RequirementDocument.objects.get(pk=document_id))
        analysis.review_run_id = run.pk
        analysis.save(update_fields=("review_run",))
        if analysis.review_status != RequirementAnalysis.StageStatus.PASSED:
            raise RequirementAnalysisConfirmationError("需求评审未通过，请先修复结构映射或验收条件问题。")
        service.complete(run, "requirement_review", {"analysis_id": str(analysis.pk), "review_status": analysis.review_status}, artifact_ref={"type": "requirement_review", "id": str(analysis.pk)})
        return {"status": "completed", "analysis_id": str(analysis.pk), "run_id": str(run.pk)}
    except RequirementAnalysisConfirmationError as exc:
        service.fail(run, "requirement_review", "review_failed", str(exc))
        return {"status": "failed", "error_code": "review_failed", "run_id": str(run.pk)}


@shared_task(bind=True, name="requirement_analysis.decompose", max_retries=2)
def run_requirement_decomposition(self, document_id: str, business_run_id: str) -> dict[str, Any]:
    """Execute the same reviewed-version gate and decomposition Service asynchronously."""
    del self
    service = BusinessSkillRunService()
    run = SkillChainRun.objects.get(pk=business_run_id)
    try:
        service.mark_running(run, "requirement_decomposition")
        analysis = RequirementAnalysisRecordService().decompose_reviewed_analysis(RequirementDocument.objects.get(pk=document_id))
        analysis.decomposition_run_id = run.pk
        analysis.save(update_fields=("decomposition_run",))
        service.complete(run, "requirement_decomposition", {"analysis_id": str(analysis.pk), "decomposition_status": analysis.decomposition_status}, artifact_ref={"type": "requirement_decomposition", "id": str(analysis.pk)})
        return {"status": "completed", "analysis_id": str(analysis.pk), "run_id": str(run.pk)}
    except RequirementAnalysisConfirmationError as exc:
        service.fail(run, "requirement_decomposition", "decomposition_failed", str(exc))
        return {"status": "failed", "error_code": "decomposition_failed", "run_id": str(run.pk)}


__all__ = [
    "TASK_TYPE", "run_requirement_analysis", "run_requirement_review", "run_requirement_decomposition", "set_requirement_runtime",
]
