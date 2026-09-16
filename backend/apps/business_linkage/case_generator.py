"""Generate reviewable multi-interface cases from recognized business linkages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


MAX_LINKAGES = 256
MAX_STEPS_PER_LINKAGE = 128


class BusinessLinkageCaseGenerationError(ValueError):
    """Raised when a linkage cannot produce a safe chained test case."""

    def __init__(self, message: str, code: str = "invalid_linkage") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BusinessLinkageCaseGenerationResult:
    """Generated chained cases and their coverage status."""

    cases: list[dict[str, Any]]
    coverage_report: dict[str, Any]


def _text(value: Any, field_name: str, *, max_length: int = 1000) -> str:
    """Return bounded text or reject a missing required value."""
    result = str(value or "").strip()
    if not result:
        raise BusinessLinkageCaseGenerationError(f"{field_name} 不能为空。")
    return result[:max_length]


def _identifier(value: Any, field_name: str) -> str:
    """Normalize a stable linkage or step identifier."""
    result = _text(value, field_name, max_length=200)
    if any(ord(char) < 32 for char in result):
        raise BusinessLinkageCaseGenerationError(f"{field_name} 包含无效控制字符。")
    return result


def _normalize_linkage(raw_linkage: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the T052 linkage shape needed for case generation."""
    linkage_id = _identifier(raw_linkage.get("id"), "链路 id")
    name = _text(raw_linkage.get("name"), "链路名称", max_length=200)
    raw_steps = raw_linkage.get("steps")
    raw_dependencies = raw_linkage.get("dependencies")
    if not isinstance(raw_steps, list) or len(raw_steps) < 2:
        raise BusinessLinkageCaseGenerationError("业务链路至少需要两个接口步骤。")
    if len(raw_steps) > MAX_STEPS_PER_LINKAGE:
        raise BusinessLinkageCaseGenerationError("单条业务链路步骤数量超过安全上限。", "input_too_large")
    if not isinstance(raw_dependencies, list) or not raw_dependencies:
        raise BusinessLinkageCaseGenerationError("业务链路至少需要一条依赖关系。")

    steps: list[dict[str, Any]] = []
    step_ids: set[str] = set()
    orders: set[int] = set()
    interface_ids: set[str] = set()
    for raw_step in raw_steps:
        if not isinstance(raw_step, Mapping):
            raise BusinessLinkageCaseGenerationError("链路步骤必须是对象。")
        step_id = _identifier(raw_step.get("id"), "步骤 id")
        interface_id = _identifier(raw_step.get("interface_id"), "接口 id")
        try:
            order = int(raw_step.get("order"))
        except (TypeError, ValueError) as exc:
            raise BusinessLinkageCaseGenerationError("步骤 order 必须是正整数。") from exc
        if step_id in step_ids or interface_id in interface_ids or order < 1 or order in orders:
            raise BusinessLinkageCaseGenerationError("步骤 id、接口 id 和 order 不能重复。")
        step_ids.add(step_id)
        interface_ids.add(interface_id)
        orders.add(order)
        steps.append(
            {
                "id": step_id,
                "interface_id": interface_id,
                "order": order,
                "purpose": str(raw_step.get("purpose") or "调用接口并检查返回结果").strip()[:500],
            }
        )

    dependency_pairs: set[tuple[str, str]] = set()
    dependency_ids: set[str] = set()
    dependencies: list[dict[str, str]] = []
    for raw_dependency in raw_dependencies:
        if not isinstance(raw_dependency, Mapping):
            raise BusinessLinkageCaseGenerationError("链路依赖必须是对象。")
        dependency_id = _identifier(raw_dependency.get("id"), "依赖 id")
        from_step = _identifier(raw_dependency.get("from_step_id"), "依赖来源步骤")
        to_step = _identifier(raw_dependency.get("to_step_id"), "依赖目标步骤")
        pair = (from_step, to_step)
        if (
            dependency_id in dependency_ids
            or from_step == to_step
            or from_step not in step_ids
            or to_step not in step_ids
            or pair in dependency_pairs
        ):
            raise BusinessLinkageCaseGenerationError("依赖必须引用不同且存在的步骤，且不能重复。")
        dependency_ids.add(dependency_id)
        dependency_pairs.add(pair)
        dependencies.append({"id": dependency_id, "from_step_id": from_step, "to_step_id": to_step})
    return {
        "id": linkage_id,
        "name": name,
        "description": str(raw_linkage.get("description") or "").strip()[:1000],
        "steps": sorted(steps, key=lambda item: item["order"]),
        "dependencies": dependencies,
    }


def _case(linkage: Mapping[str, Any], case_number: int) -> dict[str, Any]:
    """Build one deterministic, non-executing chained API case."""
    steps = linkage["steps"]
    return {
        "id": f"linkage-case-{case_number:03d}",
        "title": f"{linkage['name']} - 多接口串联主流程",
        "type": "linkage",
        "priority": "P0",
        "linkage_id": linkage["id"],
        "steps": [
            f"第{step['order']}步：调用接口 {step['interface_id']}，{step['purpose']}"
            for step in steps
        ],
        "expected_result": "链路内接口按顺序完成，后续接口能够使用前置接口产生的业务上下文；具体数据映射和断言待 T054 补充。",
        "automatable": False,
        "automation_pending": "T054_data_flow_and_assertions",
        "source_linkage_id": linkage["id"],
        "dependency_ids": [item["id"] for item in linkage["dependencies"]],
    }


def generate_linkage_cases(
    linkages: Sequence[Mapping[str, Any]],
) -> BusinessLinkageCaseGenerationResult:
    """Generate one stable primary-flow case for every valid T052 linkage."""
    if isinstance(linkages, (str, bytes)) or not isinstance(linkages, Sequence):
        raise BusinessLinkageCaseGenerationError("业务链路必须是数组。", "invalid_input")
    if not linkages:
        raise BusinessLinkageCaseGenerationError("没有可生成用例的业务链路。", "empty_input")
    if len(linkages) > MAX_LINKAGES:
        raise BusinessLinkageCaseGenerationError("业务链路数量超过安全上限。", "input_too_large")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_linkage in linkages:
        if not isinstance(raw_linkage, Mapping):
            raise BusinessLinkageCaseGenerationError("每条业务链路必须是对象。")
        linkage = _normalize_linkage(raw_linkage)
        if linkage["id"] in seen_ids:
            raise BusinessLinkageCaseGenerationError("业务链路 id 不能重复。")
        seen_ids.add(linkage["id"])
        normalized.append(linkage)
    normalized.sort(key=lambda item: item["id"])
    cases = [_case(linkage, index) for index, linkage in enumerate(normalized, start=1)]
    coverage_report = {
        "generation_method": "deterministic_linkage_primary_flow",
        "execution_status": "completed",
        "linkage_count": len(normalized),
        "case_count": len(cases),
        "covered_linkage_ids": [item["id"] for item in normalized],
        "data_flow_status": "pending_t054",
        "assertion_status": "pending_t054",
    }
    return BusinessLinkageCaseGenerationResult(cases, coverage_report)


__all__ = [
    "BusinessLinkageCaseGenerationError",
    "BusinessLinkageCaseGenerationResult",
    "generate_linkage_cases",
]
