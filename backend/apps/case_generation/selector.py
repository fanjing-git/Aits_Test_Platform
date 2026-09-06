"""Deterministic automation suitability selection for generated cases."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.case_generation.models import CaseGenerationRecord


class CaseSelectionError(ValueError):
    """Raised when a generation record has no valid cases to classify."""


@dataclass(frozen=True)
class SelectionResult:
    """Classified cases and aggregate automation recommendations."""

    cases: list[dict[str, Any]]
    summary: dict[str, Any]


def _classify(case: dict[str, Any]) -> dict[str, Any]:
    """Annotate one case with automation, difficulty, stack and priority."""
    text = f"{case.get('title', '')} {' '.join(str(step) for step in case.get('steps', []) if step)}".casefold()
    manual_markers = ("人工", "验证码", "captcha", "视觉", "截图", "manual", "external")
    linkage = case.get("type") == "linkage" or case.get("linkage_id")
    automatable = not linkage and not any(marker in text for marker in manual_markers)
    step_count = len(case.get("steps", [])) if isinstance(case.get("steps"), list) else 1
    difficulty = "high" if linkage or step_count >= 5 else "medium" if step_count >= 3 or case.get("type") in {"negative", "boundary"} else "low"
    if linkage:
        stack = ["pytest", "requests", "workflow-fixture"]
    elif any(marker in text for marker in ("页面", "浏览器", "按钮", "ui", "view")):
        stack = ["Playwright"]
    else:
        stack = ["pytest", "requests"]
    priority = "P0" if case.get("type") in {"positive", "linkage"} else "P1"
    return {**case, "automatable": automatable, "automation_difficulty": difficulty, "recommended_stack": stack, "priority": priority, "automation_reason": "跨模块或人工交互场景需人工执行" if not automatable else "步骤稳定且可由受控测试工具执行"}


def select_automatable_cases(cases: list[dict[str, Any]]) -> SelectionResult:
    """Classify generated cases and return a stable automation recommendation."""
    if not isinstance(cases, list) or not cases:
        raise CaseSelectionError("没有可筛选的测试用例。")
    classified = [_classify(case) for case in cases if isinstance(case, dict) and case.get("id")]
    if not classified:
        raise CaseSelectionError("测试用例缺少有效编号。")
    summary = {
        "total": len(classified),
        "automatable": sum(1 for item in classified if item["automatable"]),
        "manual": sum(1 for item in classified if not item["automatable"]),
        "difficulty": {level: sum(1 for item in classified if item["automation_difficulty"] == level) for level in ("low", "medium", "high")},
        "priority": {level: sum(1 for item in classified if item["priority"] == level) for level in ("P0", "P1", "P2")},
    }
    summary["automation_rate"] = round(summary["automatable"] / summary["total"], 4)
    return SelectionResult(classified, summary)


def select_generation_record(record: CaseGenerationRecord) -> CaseGenerationRecord:
    """Persist automation selection metadata and refreshed auto/manual counts."""
    result = select_automatable_cases(record.cases)
    record.cases = result.cases
    record.auto_cases = result.summary["automatable"]
    record.manual_cases = result.summary["manual"]
    record.coverage_report = {**(record.coverage_report if isinstance(record.coverage_report, dict) else {}), "automation_selection": result.summary}
    record.save(update_fields=("cases", "auto_cases", "manual_cases", "coverage_report"))
    return record


__all__ = ["CaseSelectionError", "SelectionResult", "select_automatable_cases", "select_generation_record"]
