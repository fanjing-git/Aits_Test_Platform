"""Manual correction and confirmation of reviewed test cases."""

import copy
import re
from typing import Any, Mapping, Sequence

from django.db import transaction
from django.utils import timezone

from apps.case_generation.design_methods import design_method_label, legacy_case_type, normalize_design_method
from apps.case_generation.models import CaseGenerationRecord
from apps.requirement_analysis.models import RequirementAnalysis


class ReviewEditingError(ValueError):
    """Raised when a manual review correction cannot be persisted safely."""


def _text(value: Any, field: str, *, required: bool = True) -> str:
    """Normalize a user-editable text field and reject missing required values."""
    result = str(value or "").strip()
    if required and not result:
        raise ReviewEditingError(f"{field}不能为空。")
    return result


def _steps(value: Any) -> list[str]:
    """Normalize manual steps to a non-empty list of executable instructions."""
    if isinstance(value, str):
        result = [line.strip() for line in value.splitlines() if line.strip()]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        result = [str(item).strip() for item in value if str(item).strip()]
    else:
        result = []
    if not result:
        raise ReviewEditingError("测试步骤不能为空。")
    return result


def _next_case_id(cases: list[dict[str, Any]]) -> str:
    """Return the next stable case ID while preserving existing custom IDs."""
    used = {str(item.get("id") or "") for item in cases}
    numbers = [int(match.group(1)) for value in used if (match := re.fullmatch(r"case-(\d+)", value))]
    number = max(numbers, default=0) + 1
    candidate = f"case-{number:03d}"
    while candidate in used:
        number += 1
        candidate = f"case-{number:03d}"
    return candidate


def _manual_case(raw: Mapping[str, Any], case_id: str, *, round_added: int, source_module_id: str) -> dict[str, Any]:
    """Build a validated manually added case with the normal case contract."""
    method = normalize_design_method(raw.get("test_design_method") or raw.get("type") or "positive")
    case_type = legacy_case_type(method, linkage=str(raw.get("type") or "") == "linkage")
    return {
        "id": case_id,
        "title": _text(raw.get("title"), "用例标题"),
        "type": case_type,
        "test_design_method": method,
        "test_design_method_label": design_method_label(method),
        "priority": _text(raw.get("priority") or "P1", "优先级"),
        "steps": _steps(raw.get("steps")),
        "expected_result": _text(raw.get("expected_result"), "预期结果"),
        "automatable": bool(raw.get("automatable", False)),
        "source_function_id": str(raw.get("source_function_id") or "").strip(),
        "source_module_id": source_module_id,
        "source_test_point_id": raw.get("source_test_point_id"),
        "evidence_ids": list(raw.get("evidence_ids") or []),
        "round_added": round_added,
        "manual_added": True,
        "manual_review_status": "manual_final",
        "manual_revision_label": "人工修订用例",
    }


def _analysis_scope(record: CaseGenerationRecord) -> tuple[dict[str, dict[str, Any]], set[str], set[str]]:
    """Return the current function, module and test-point scope for safe linkage edits."""
    analysis = record.document.analyses.order_by("-created_at").first()
    if not isinstance(analysis, RequirementAnalysis):
        raise ReviewEditingError("需求分析结果不存在，无法保存关联功能点。")
    functions = {
        str(item.get("id")): dict(item)
        for item in (analysis.functions or [])
        if isinstance(item, Mapping) and item.get("id")
    }
    modules = {
        str(item.get("id"))
        for item in (analysis.modules or [])
        if isinstance(item, Mapping) and item.get("id")
    }
    test_points = {
        str(item.get("id")): str(item.get("function_id") or item.get("source_function_id") or "")
        for item in (analysis.test_points or [])
        if isinstance(item, Mapping) and item.get("id")
    }
    if not functions:
        raise ReviewEditingError("当前需求分析没有可关联的功能点。")
    return functions, modules, test_points


def _validated_linkage(
    raw: Mapping[str, Any],
    *,
    functions: Mapping[str, Mapping[str, Any]],
    modules: set[str],
    test_points: Mapping[str, str],
    existing: Mapping[str, Any] | None = None,
    required: bool = False,
) -> tuple[str, str] | None:
    """Validate a manual case's function/test-point association and return IDs."""
    has_function_field = "source_function_id" in raw
    function_id = str(raw.get("source_function_id") if has_function_field else (existing or {}).get("source_function_id") or "").strip()
    if not function_id:
        if required and not has_function_field and functions:
            # Preserve the legacy API that omitted the association while still
            # persisting a valid, deterministic function link for new cases.
            function_id = next(iter(functions))
        elif has_function_field:
            raise ReviewEditingError("请为人工用例选择有效的关联功能点。")
        else:
            return None
    if function_id not in functions:
        raise ReviewEditingError("关联功能点不属于当前需求分析结果。")
    module_id = str(functions[function_id].get("module_id") or "").strip()
    if module_id and module_id not in modules:
        raise ReviewEditingError("关联功能点的模块不属于当前需求分析结果。")
    requested_module = str(raw.get("source_module_id") or "").strip()
    if requested_module and requested_module != module_id:
        raise ReviewEditingError("关联模块与功能点归属不一致。")
    if "source_test_point_id" in raw and raw.get("source_test_point_id"):
        test_point_id = str(raw.get("source_test_point_id")).strip()
        if test_point_id not in test_points:
            raise ReviewEditingError("关联测试点不属于当前需求分析结果。")
        if test_points[test_point_id] and test_points[test_point_id] != function_id:
            raise ReviewEditingError("关联测试点与功能点归属不一致。")
    return function_id, module_id


@transaction.atomic
def save_reviewed_cases(
    record: CaseGenerationRecord,
    updates: Sequence[Mapping[str, Any]],
    additions: Sequence[Mapping[str, Any]],
) -> CaseGenerationRecord:
    """Persist manual corrections and additions, then require a fresh review.

    The first save stores a deep copy of the generated cases in the JSON audit
    record. Existing IDs are updated in place; new cases receive the next
    ``case-NNN`` ID and are appended to the current case list.
    """
    functions, modules, test_points = _analysis_scope(record)
    current = [copy.deepcopy(item) for item in record.cases if isinstance(item, dict)]
    by_id = {str(item.get("id")): item for item in current if item.get("id")}
    if not updates and not additions:
        raise ReviewEditingError("请至少修改一条用例或新增一条用例后再保存。")

    updated_ids: list[str] = []
    for raw in updates:
        case_id = _text(raw.get("id"), "用例编号")
        if case_id not in by_id:
            raise ReviewEditingError(f"用例 {case_id} 不存在，无法保存修订。")
        target = by_id[case_id]
        linkage = _validated_linkage(
            raw,
            functions=functions,
            modules=modules,
            test_points=test_points,
            existing=target,
        )
        if linkage:
            target["source_function_id"], target["source_module_id"] = linkage
        if "source_test_point_id" in raw:
            target["source_test_point_id"] = raw.get("source_test_point_id")
        if "title" in raw:
            target["title"] = _text(raw.get("title"), "用例标题")
        if "steps" in raw:
            target["steps"] = _steps(raw.get("steps"))
        if "expected_result" in raw:
            target["expected_result"] = _text(raw.get("expected_result"), "预期结果")
        if "priority" in raw:
            target["priority"] = _text(raw.get("priority"), "优先级")
        if "automatable" in raw:
            target["automatable"] = bool(raw.get("automatable"))
        if "test_design_method" in raw or "type" in raw:
            method = normalize_design_method(raw.get("test_design_method") or raw.get("type"))
            target["test_design_method"] = method
            target["test_design_method_label"] = design_method_label(method)
            target["type"] = legacy_case_type(method, linkage=str(raw.get("type") or target.get("type")) == "linkage")
        target["manual_revised"] = True
        target["manual_review_status"] = "manual_final"
        target["manual_revision_label"] = "人工修订用例"
        target["manual_revised_at"] = timezone.now().isoformat()
        updated_ids.append(case_id)

    added_ids: list[str] = []
    for raw in additions:
        case_id = _next_case_id(current)
        linkage = _validated_linkage(
            raw,
            functions=functions,
            modules=modules,
            test_points=test_points,
            required=True,
        )
        assert linkage is not None
        item = _manual_case(raw, case_id, round_added=int(record.rounds or 0), source_module_id=linkage[1])
        current.append(item)
        by_id[case_id] = item
        added_ids.append(case_id)

    previous_revision = record.review_report.get("manual_revision") if isinstance(record.review_report, dict) else None
    original_cases = previous_revision.get("original_cases") if isinstance(previous_revision, dict) else None
    if not isinstance(original_cases, list):
        original_cases = copy.deepcopy(record.cases)
    revision_number = int(previous_revision.get("revision_number", 0)) + 1 if isinstance(previous_revision, dict) else 1
    revision = {
        "status": "saved_pending_review",
        "revision_number": revision_number,
        "saved_at": timezone.now().isoformat(),
        "updated_case_ids": sorted(set(updated_ids)),
        "added_case_ids": added_ids,
        "original_case_count": len(original_cases),
        "current_case_count": len(current),
        "original_cases": original_cases,
    }
    report = copy.deepcopy(record.review_report) if isinstance(record.review_report, dict) else {}
    report["manual_revision"] = revision
    report["approved"] = False
    report["execution_status"] = "pending_rerun"
    report["manual_revision_message"] = "已保存人工修订，需重新评审后才能确认通过。"
    coverage = copy.deepcopy(record.coverage_report) if isinstance(record.coverage_report, dict) else {}
    previous_selection = coverage.pop("automation_selection", None)
    invalidation_history = coverage.get("automation_selection_invalidation_history")
    if not isinstance(invalidation_history, list):
        invalidation_history = []
    if isinstance(previous_selection, dict):
        invalidation_history.append({
            "invalidated_at": revision["saved_at"],
            "reason": "manual_revision",
            "previous_selection": previous_selection,
        })
    coverage["automation_selection_invalidation_history"] = invalidation_history[-20:]
    coverage["automation_selection_invalidated"] = {
        "invalidated_at": revision["saved_at"],
        "reason": "manual_revision",
        "updated_case_ids": sorted(set(updated_ids)),
        "added_case_ids": added_ids,
    }
    coverage["manual_revision"] = {key: value for key, value in revision.items() if key != "original_cases"}
    record.cases = current
    record.total_cases = len(current)
    record.auto_cases = sum(1 for item in current if item.get("automatable"))
    record.manual_cases = record.total_cases - record.auto_cases
    record.review_rounds = 0
    record.review_report = report
    record.coverage_report = coverage
    record.save(update_fields=("cases", "total_cases", "auto_cases", "manual_cases", "review_rounds", "review_report", "coverage_report"))
    return record


__all__ = ["ReviewEditingError", "save_reviewed_cases"]
