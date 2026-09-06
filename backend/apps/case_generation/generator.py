"""Deterministic five-round test case generation from requirement analysis."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from django.db import transaction

from apps.case_generation.models import CaseGenerationRecord
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument


class CaseGenerationError(ValueError):
    """Raised when an analysis cannot be converted to test cases."""


@dataclass(frozen=True)
class CaseGenerationResult:
    """Final cases, coverage and a trace of the five generation rounds."""

    cases: list[dict[str, Any]]
    coverage_report: dict[str, Any]
    round_trace: list[dict[str, Any]]


def _analysis_payload(value: RequirementAnalysis | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(value, RequirementAnalysis):
        return {"modules": value.modules, "functions": value.functions, "linkages": value.linkages, "test_points": value.test_points}
    if not isinstance(value, Mapping):
        raise CaseGenerationError("需求分析结果格式无效。")
    return value


def _case(function: Mapping[str, Any], kind: str, round_added: int, *, linkage: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build one safe, reviewable test case without executing a target system."""
    name = str(function.get("name") or function.get("description") or "未命名功能").strip()
    labels = {"positive": "正常流程", "negative": "异常与权限", "boundary": "边界条件", "linkage": "跨模块联动"}
    return {
        "id": "",
        "title": f"{name} - {labels[kind]}",
        "type": kind,
        "priority": "P0" if kind in {"positive", "linkage"} else "P1",
        "source_function_id": function.get("id"),
        "steps": [f"准备{function.get('module_id', '目标模块')}所需数据", f"执行{name}"],
        "expected_result": f"{name}符合需求并返回可验证结果",
        "automatable": kind != "linkage",
        "round_added": round_added,
        "linkage_id": linkage.get("id") if linkage else None,
    }


def generate_cases(analysis: RequirementAnalysis | Mapping[str, Any]) -> CaseGenerationResult:
    """Run initial generation, comparison, gap fill, correction and confirmation."""
    payload = _analysis_payload(analysis)
    functions = payload.get("functions")
    if not isinstance(functions, list) or not functions:
        raise CaseGenerationError("需求分析结果没有可生成用例的功能点。")
    functions = [item for item in functions if isinstance(item, Mapping) and item.get("id")]
    if not functions:
        raise CaseGenerationError("功能点缺少有效标识。")
    cases: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    # Round 1: one positive path per function.
    cases.extend(_case(function, "positive", 1) for function in functions)
    trace.append({"round": 1, "stage": "initial", "added": len(cases), "note": "每个功能点生成正常流程"})
    # Round 2: compare each function against the required negative/boundary coverage.
    before = len(cases)
    for function in functions:
        cases.extend((_case(function, "negative", 2), _case(function, "boundary", 2)))
    trace.append({"round": 2, "stage": "requirement_compare", "added": len(cases) - before, "note": "补齐异常和边界覆盖"})
    # Round 3: use T044 linkages to add cross-module scenarios.
    before = len(cases)
    by_id = {item["id"]: item for item in functions}
    for linkage in payload.get("linkages", []) if isinstance(payload.get("linkages"), list) else []:
        if not isinstance(linkage, Mapping):
            continue
        source = by_id.get(linkage.get("from")) or by_id.get(linkage.get("source_function_id"))
        if source:
            cases.append(_case(source, "linkage", 3, linkage=linkage))
    trace.append({"round": 3, "stage": "gap_fill", "added": len(cases) - before, "note": "补齐跨模块联动"})
    # Round 4: correct duplicate or incomplete drafts deterministically.
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in cases:
        key = (str(item.get("source_function_id")), str(item.get("type")))
        unique.setdefault(key, item)
    cases = list(unique.values())
    for item in cases:
        item["steps"] = [step for step in item.get("steps", []) if str(step).strip()]
        item["expected_result"] = str(item.get("expected_result") or "结果可验证").strip()
    trace.append({"round": 4, "stage": "deviation_correction", "added": 0, "note": "去重并修正必填字段"})
    # Round 5: assign stable IDs and final coverage report.
    cases.sort(key=lambda item: (str(item.get("source_function_id")), str(item.get("type"))))
    for index, item in enumerate(cases, start=1):
        item["id"] = f"case-{index:03d}"
    types = {kind: sum(item["type"] == kind for item in cases) for kind in ("positive", "negative", "boundary", "linkage")}
    coverage = {"function_count": len(functions), "case_count": len(cases), "types": types, "covered_function_ids": sorted({str(item["source_function_id"]) for item in cases}), "coverage_rate": round(len({str(item["source_function_id"]) for item in cases}) / len(functions), 4)}
    trace.append({"round": 5, "stage": "final_confirmation", "added": 0, "note": "稳定排序并输出覆盖度"})
    return CaseGenerationResult(cases, coverage, trace)


@transaction.atomic
def generate_document_cases(document: RequirementDocument, analysis: RequirementAnalysis | None = None) -> CaseGenerationRecord:
    """Persist one five-round generation run for a project requirement document."""
    source = analysis or document.analyses.order_by("-created_at").first()
    if source is None:
        raise CaseGenerationError("需求文档尚未完成需求分析。")
    record = CaseGenerationRecord.objects.create(project=document.project, document=document, status=CaseGenerationRecord.Status.GENERATING)
    try:
        result = generate_cases(source)
        record.rounds = 5
        record.total_cases = len(result.cases)
        record.auto_cases = sum(1 for item in result.cases if item["automatable"])
        record.manual_cases = record.total_cases - record.auto_cases
        record.cases = result.cases
        record.coverage_report = {**result.coverage_report, "round_trace": result.round_trace}
        record.status = CaseGenerationRecord.Status.COMPLETED
        record.save(update_fields=("rounds", "total_cases", "auto_cases", "manual_cases", "cases", "coverage_report", "status"))
    except CaseGenerationError:
        record.status = CaseGenerationRecord.Status.FAILED
        record.save(update_fields=("status",))
        raise
    return record


__all__ = ["CaseGenerationError", "CaseGenerationResult", "generate_cases", "generate_document_cases"]
