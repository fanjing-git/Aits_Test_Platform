"""Five-round test case review with explicit model and fallback states."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from apps.case_generation.llm_adapter import CaseReviewModelAdapter
from apps.case_generation.models import CaseGenerationRecord
from apps.configs.models import ModelRoutingPolicy
from apps.configs.routing import ModelRouteError, ModelRouteResolver
from apps.requirement_analysis.llm_adapter import ModelAnalysisError


class CaseReviewError(ValueError):
    """Raised when a generation record cannot be reviewed."""


@dataclass(frozen=True)
class ReviewResult:
    """Final review decision and the five-round evidence trail."""

    approved: bool
    issues: list[dict[str, Any]]
    round_trace: list[dict[str, Any]]
    report: dict[str, Any]


def _issue_signature(item: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    """Return a stable signature for de-duplicating review findings."""
    return (
        str(item.get("case_id", "")),
        str(item.get("code", "")),
        str(item.get("severity", "")),
        str(item.get("description", "")),
        str(item.get("suggestion", "")),
    )


def _deterministic_issues(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run deterministic structure and scenario coverage checks."""
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in cases:
        case_id = str(item.get("id", ""))
        if not case_id or case_id in seen:
            issues.append({"code": "duplicate_or_missing_id", "case_id": case_id, "severity": "high"})
        seen.add(case_id)
        for field in ("title", "type", "steps", "expected_result"):
            if not item.get(field):
                issues.append({"code": "missing_field", "case_id": case_id, "field": field, "severity": "high"})
    by_function: dict[str, set[str]] = {}
    for item in cases:
        by_function.setdefault(str(item.get("source_function_id")), set()).add(str(item.get("type")))
    for function_id, kinds in by_function.items():
        missing = {"positive", "negative", "boundary"} - kinds
        if missing:
            issues.append({"code": "coverage_gap", "function_id": function_id, "missing_types": sorted(missing), "severity": "medium"})
    return issues


def _approval(issues: list[dict[str, Any]]) -> bool:
    """Return whether no high or medium findings remain."""
    return not any(item.get("severity") in {"high", "medium"} for item in issues)


def review_cases(
    record: CaseGenerationRecord,
    *,
    model_adapter: CaseReviewModelAdapter | None = None,
    preferred_model_name: str | None = None,
    allow_deterministic_baseline: bool = True,
    route_metadata: Mapping[str, Any] | None = None,
) -> ReviewResult:
    """Review cases for completeness, coverage, consistency and risk."""
    if not isinstance(record.cases, list) or not record.cases:
        raise CaseReviewError("生成记录没有可评审的用例。")
    cases = [item for item in record.cases if isinstance(item, dict)]
    issues = _deterministic_issues(cases)
    trace: list[dict[str, Any]] = []
    model_results: list[dict[str, Any]] = []
    model_warning = ""
    fallback_used = False

    if model_adapter:
        for review_round in range(1, 6):
            try:
                model_result = model_adapter.review(
                    record=record,
                    project_name=record.project.name,
                    round_number=review_round,
                    existing_issues=issues,
                    existing_corrections=[],
                    preferred_model_name=preferred_model_name,
                )
                model_results.append(model_result)
                round_entry: dict[str, Any] = {
                    "round": review_round,
                    "stage": "model_review",
                    "status": "completed",
                    "model_status": "completed",
                    "issues": len(issues),
                    "model_issue_count": len(model_result.get("issues", [])),
                    "correction_count": len(model_result.get("corrections", [])),
                }
                coverage = model_result.get("coverage_report") if isinstance(model_result, dict) else None
                if isinstance(coverage, dict):
                    if isinstance(coverage.get("structured_generation"), dict):
                        round_entry["structured_generation"] = coverage["structured_generation"]
                    if isinstance(coverage.get("model_route"), dict):
                        round_entry["model_route"] = coverage["model_route"]
                trace.append(round_entry)
            except ModelAnalysisError as exc:
                failure = {
                    "round": review_round,
                    "stage": "model_failed",
                    "status": "failed",
                    "model_status": "failed",
                    "error_code": getattr(exc, "code", "model_error"),
                    "structured_generation": {
                        "status": "partial" if getattr(exc, "structured_trace", ()) else "failed",
                        "segments": [dict(item) for item in getattr(exc, "structured_trace", ())],
                    },
                    "issues": len(issues),
                }
                if not allow_deterministic_baseline:
                    error = CaseReviewError(f"第{review_round}轮模型评审失败，未生成确定性替代结果：{exc}")
                    error.partial_issues = list(issues)
                    error.partial_round_trace = [*trace, failure]
                    error.structured_trace = list(exc.structured_trace)
                    raise error from exc
                fallback_used = True
                model_warning = str(exc)
                trace.append(failure)
                for remaining in range(review_round + 1, 6):
                    trace.append({
                        "round": remaining,
                        "stage": "deterministic_fallback",
                        "status": "completed",
                        "model_status": "not_run_after_failure",
                        "issues": len(issues),
                    })
                break

        issue_signatures = {_issue_signature(item) for item in issues}
        for model_result in model_results:
            for issue in model_result.get("issues", []):
                signature = _issue_signature(issue)
                if signature not in issue_signatures:
                    issues.append(issue)
                    issue_signatures.add(signature)
    else:
        stages = ("initial_review", "requirement_compare", "deviation_correction", "re_review", "final_review_report")
        for index, stage in enumerate(stages, start=1):
            corrected = 0
            if index == 3:
                for item in cases:
                    if not isinstance(item.get("steps"), list):
                        item["steps"] = [str(item["steps"])]
                        corrected += 1
                    item["title"] = str(item.get("title") or "未命名用例").strip()
                    item["expected_result"] = str(item.get("expected_result") or "结果可验证").strip()
            entry: dict[str, Any] = {
                "round": index,
                "stage": stage,
                "status": "completed",
                "model_status": "not_configured",
                "issues": len(issues),
            }
            if corrected:
                entry["corrected"] = corrected
            trace.append(entry)

    approved = _approval(issues)
    method = "model_verified" if len(model_results) == 5 and not fallback_used else ("deterministic_fallback" if fallback_used else "deterministic_baseline")
    report: dict[str, Any] = {
        "approved": approved,
        "case_count": len(cases),
        "issue_count": len(issues),
        "high_issue_count": sum(item.get("severity") == "high" for item in issues),
        "medium_issue_count": sum(item.get("severity") == "medium" for item in issues),
        "round_trace": trace,
        "analysis_method": method,
        "execution_status": "completed",
        "model_rounds": list(range(1, len(model_results) + 1)),
        "model_round_statuses": [
            {"round": item["round"], "status": item.get("model_status", item.get("status")), "error_code": item.get("error_code", "")}
            for item in trace
            if item.get("stage") in {"model_review", "model_failed"}
        ],
    }
    if route_metadata:
        report["model_route_resolution"] = dict(route_metadata)
    if model_results:
        report["model_summary"] = "；".join(item.get("summary", "") for item in model_results if item.get("summary"))
        report["model_corrections"] = [correction for item in model_results for correction in item.get("corrections", [])]
        report["model_segment_traces"] = [
            item["coverage_report"]["structured_generation"]
            for item in model_results
            if isinstance(item.get("coverage_report"), dict)
            and isinstance(item["coverage_report"].get("structured_generation"), dict)
        ]
    if model_warning:
        report["model_warning"] = model_warning
    return ReviewResult(approved, issues, trace[:5], report)


def review_generation_record(
    record: CaseGenerationRecord,
    *,
    model_adapter: CaseReviewModelAdapter | None = None,
    preferred_model_name: str | None = None,
) -> CaseGenerationRecord:
    """Persist a five-round review report while retaining generated cases."""
    record.status = CaseGenerationRecord.Status.REVIEWING
    record.save(update_fields=("status",))
    route = None
    try:
        try:
            route = ModelRouteResolver().resolve(
                ModelRoutingPolicy.FeatureKey.CASE_REVIEW,
                preferred_name=preferred_model_name,
            )
        except ModelRouteError as exc:
            raise CaseReviewError(f"用例评审模型路由不可用：{exc}") from exc
        has_compatible_model = route.available
        if model_adapter is None and has_compatible_model:
            model_adapter = CaseReviewModelAdapter()
        result = review_cases(
            record,
            model_adapter=model_adapter,
            preferred_model_name=preferred_model_name,
            allow_deterministic_baseline=not has_compatible_model,
            route_metadata=route.as_dict(),
        )
        record.review_rounds = 5
        record.review_report = {**result.report, "issues": result.issues, "round_trace": result.round_trace}
        record.status = CaseGenerationRecord.Status.COMPLETED
        record.save(update_fields=("review_rounds", "review_report", "status"))
    except (CaseReviewError, ModelAnalysisError) as exc:
        partial_issues = getattr(exc, "partial_issues", None)
        partial_trace = getattr(exc, "partial_round_trace", [])
        if isinstance(partial_issues, list):
            record.review_rounds = len(partial_trace) if isinstance(partial_trace, list) else 0
            record.review_report = {
                "approved": False,
                "analysis_method": "model_partial",
                "execution_status": "failed",
                "partial_result": True,
                "issues": partial_issues,
                "round_trace": partial_trace,
                "model_segment_traces": getattr(exc, "structured_trace", []),
                "model_route_resolution": route.as_dict() if route else {},
            }
            record.save(update_fields=("review_rounds", "review_report", "status"))
        record.status = CaseGenerationRecord.Status.FAILED
        record.save(update_fields=("status",))
        raise
    return record


__all__ = ["CaseReviewError", "ReviewResult", "review_cases", "review_generation_record"]
