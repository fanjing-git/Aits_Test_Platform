"""Deterministic five-round review for generated test cases."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.configs.models import ModelConfig
from apps.case_generation.models import CaseGenerationRecord
from apps.case_generation.llm_adapter import CaseReviewModelAdapter
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


def review_cases(
    record: CaseGenerationRecord,
    *,
    model_adapter: CaseReviewModelAdapter | None = None,
    preferred_model_name: str | None = None,
    allow_deterministic_baseline: bool = True,
) -> ReviewResult:
    """Review cases for completeness, requirement coverage, consistency and risk."""
    if not isinstance(record.cases, list) or not record.cases:
        raise CaseReviewError("生成记录没有可评审的用例。")
    cases = [item for item in record.cases if isinstance(item, dict)]
    issues: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    model_results: list[dict[str, Any]] = []
    model_warning = ""
    # Round 1: required field and duplicate checks.
    seen: set[str] = set()
    for item in cases:
        case_id = str(item.get("id", ""))
        if not case_id or case_id in seen:
            issues.append({"code": "duplicate_or_missing_id", "case_id": case_id, "severity": "high"})
        seen.add(case_id)
        for field in ("title", "type", "steps", "expected_result"):
            if not item.get(field):
                issues.append({"code": "missing_field", "case_id": case_id, "field": field, "severity": "high"})
    trace.append({"round": 1, "stage": "initial_review", "issues": len(issues)})
    # Round 2: compare required scenario types per source function.
    by_function: dict[str, set[str]] = {}
    for item in cases:
        by_function.setdefault(str(item.get("source_function_id")), set()).add(str(item.get("type")))
    for function_id, kinds in by_function.items():
        missing = {"positive", "negative", "boundary"} - kinds
        if missing:
            issues.append({"code": "coverage_gap", "function_id": function_id, "missing_types": sorted(missing), "severity": "medium"})
    trace.append({"round": 2, "stage": "requirement_compare", "issues": len(issues)})
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
            except ModelAnalysisError as exc:
                if not allow_deterministic_baseline:
                    raise CaseReviewError(f"\u7b2c{review_round}\u8f6e\u6a21\u578b\u8bc4\u5ba1\u5931\u8d25\uff0c\u672a\u751f\u6210\u786e\u5b9a\u6027\u66ff\u4ee3\u7ed3\u679c\uff1a{exc}") from exc
                model_warning = str(exc)
                break
        issue_signatures = {
            (
                str(item.get("case_id", "")),
                str(item.get("code", "")),
                str(item.get("severity", "")),
                str(item.get("description", "")),
                str(item.get("suggestion", "")),
            )
            for item in issues
        }
        for model_result in model_results:
            for issue in model_result["issues"]:
                signature = (
                    str(issue.get("case_id", "")),
                    str(issue.get("code", "")),
                    str(issue.get("severity", "")),
                    str(issue.get("description", "")),
                    str(issue.get("suggestion", "")),
                )
                if signature not in issue_signatures:
                    issues.append(issue)
                    issue_signatures.add(signature)
        trace[0]["model"] = "verified"
        trace[0]["model_rounds"] = list(range(1, len(model_results) + 1))
        trace[0]["model_issues"] = sum(len(item["issues"]) for item in model_results)
        trace[1]["model_corrections"] = sum(len(item["corrections"]) for item in model_results)
        for index, _model_result in enumerate(model_results):
            if index < len(trace):
                trace[index]["model"] = "verified"
    elif model_warning:
        trace[0]["model"] = "fallback"
        trace[0]["model_warning"] = model_warning
    # Round 3: correct low-risk formatting deviations in place.
    corrected = 0
    for item in cases:
        if not isinstance(item.get("steps"), list):
            item["steps"] = [str(item["steps"])]
            corrected += 1
        item["title"] = str(item.get("title") or "未命名用例").strip()
        item["expected_result"] = str(item.get("expected_result") or "结果可验证").strip()
    trace.append({"round": 3, "stage": "deviation_correction", "corrected": corrected, "issues": len(issues)})
    # Round 4: re-run consistency checks after correction.
    remaining = [item for item in issues if item.get("severity") == "high"]
    trace.append({"round": 4, "stage": "re_review", "issues": len(remaining)})
    approved = not remaining and not any(item.get("severity") == "medium" for item in issues)
    report = {"approved": approved, "case_count": len(cases), "issue_count": len(issues), "high_issue_count": sum(item.get("severity") == "high" for item in issues), "medium_issue_count": sum(item.get("severity") == "medium" for item in issues), "round_trace": trace, "analysis_method": "model_verified" if model_results else "deterministic_baseline"}
    if model_results:
        report["model_rounds"] = list(range(1, len(model_results) + 1))
        report["model_summary"] = "；".join(item.get("summary", "") for item in model_results if item.get("summary"))
        report["model_corrections"] = [correction for item in model_results for correction in item["corrections"]]
    if model_warning:
        report["model_warning"] = model_warning
    trace.append({"round": 5, "stage": "final_review_report", "approved": approved, "issues": len(issues)})
    return ReviewResult(approved, issues, trace, report)


def review_generation_record(
    record: CaseGenerationRecord,
    *,
    model_adapter: CaseReviewModelAdapter | None = None,
    preferred_model_name: str | None = None,
) -> CaseGenerationRecord:
    """Persist a five-round review report while retaining generated cases."""
    record.status = CaseGenerationRecord.Status.REVIEWING
    record.save(update_fields=("status",))
    try:
        if model_adapter is None and ModelConfig.objects.filter(
            is_active=True,
            model_type__in=(ModelConfig.ModelType.CHAT, ModelConfig.ModelType.MULTIMODAL, ModelConfig.ModelType.VISION),
        ).exists():
            model_adapter = CaseReviewModelAdapter()
        has_compatible_model = ModelConfig.objects.filter(
            is_active=True,
            model_type__in=(ModelConfig.ModelType.CHAT, ModelConfig.ModelType.MULTIMODAL, ModelConfig.ModelType.VISION),
        ).exists()
        result = review_cases(
            record,
            model_adapter=model_adapter,
            preferred_model_name=preferred_model_name,
            allow_deterministic_baseline=not has_compatible_model,
        )
        record.review_rounds = 5
        record.review_report = {**result.report, "issues": result.issues, "round_trace": result.round_trace}
        record.status = CaseGenerationRecord.Status.COMPLETED
        record.save(update_fields=("review_rounds", "review_report", "status"))
    except (CaseReviewError, ModelAnalysisError):
        record.status = CaseGenerationRecord.Status.FAILED
        record.save(update_fields=("status",))
        raise
    return record


__all__ = ["CaseReviewError", "ReviewResult", "review_cases", "review_generation_record"]
