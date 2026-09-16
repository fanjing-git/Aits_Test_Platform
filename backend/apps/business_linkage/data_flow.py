"""Design data transfer and assertions for generated business-linkage cases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


MAX_FLOW_MAPPINGS_PER_LINKAGE = 512


class BusinessLinkageDataFlowError(ValueError):
    """Raised when a linkage cannot be converted into safe flow assertions."""

    def __init__(self, message: str, code: str = "invalid_data_flow") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BusinessLinkageDataFlowResult:
    """Enriched linkage cases and their design coverage report."""

    cases: list[dict[str, Any]]
    coverage_report: dict[str, Any]


def _required_text(value: Any, field_name: str, *, max_length: int = 300) -> str:
    """Return bounded mapping text without retaining arbitrary example values."""
    result = str(value or "").strip()
    if not result or any(ord(char) < 32 for char in result):
        raise BusinessLinkageDataFlowError(f"{field_name} 不能为空且不能包含控制字符。", "invalid_input")
    return result[:max_length]


def _field_kind(source_field: str, target_field: str) -> str:
    """Classify a field transfer for diagnostics without guessing its value."""
    text = f"{source_field} {target_field}".casefold()
    if any(term in text for term in ("token", "authorization", "cookie", "session")):
        return "token"
    if any(term in text for term in ("id", "code", "number")):
        return "identifier"
    if "status" in text or "state" in text:
        return "status"
    return "value"


def _target_location(field_name: str) -> str:
    """Choose a request location from a field name, never from a field value."""
    normalized = field_name.casefold()
    if any(term in normalized for term in ("authorization", "token", "cookie", "session")):
        return "request.headers"
    return "request.body"


def _normalize_linkage(raw_linkage: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the subset of T052 output required for T054 design."""
    linkage_id = _required_text(raw_linkage.get("id"), "链路 id", max_length=200)
    name = _required_text(raw_linkage.get("name"), "链路名称", max_length=200)
    raw_steps = raw_linkage.get("steps")
    raw_dependencies = raw_linkage.get("dependencies")
    if not isinstance(raw_steps, list) or len(raw_steps) < 2:
        raise BusinessLinkageDataFlowError("链路至少需要两个步骤。", "invalid_linkage")
    if not isinstance(raw_dependencies, list) or not raw_dependencies:
        raise BusinessLinkageDataFlowError("链路至少需要一条依赖关系。", "invalid_linkage")

    steps: list[dict[str, Any]] = []
    step_by_id: dict[str, dict[str, Any]] = {}
    for raw_step in raw_steps:
        if not isinstance(raw_step, Mapping):
            raise BusinessLinkageDataFlowError("链路步骤必须是对象。", "invalid_linkage")
        step_id = _required_text(raw_step.get("id"), "步骤 id", max_length=200)
        interface_id = _required_text(raw_step.get("interface_id"), "接口 id", max_length=200)
        try:
            order = int(raw_step.get("order"))
        except (TypeError, ValueError) as exc:
            raise BusinessLinkageDataFlowError("步骤 order 必须是正整数。", "invalid_linkage") from exc
        if step_id in step_by_id or order < 1:
            raise BusinessLinkageDataFlowError("步骤 id 不能重复且 order 必须为正整数。", "invalid_linkage")
        step = {"id": step_id, "interface_id": interface_id, "order": order}
        step_by_id[step_id] = step
        steps.append(step)
    if len({step["order"] for step in steps}) != len(steps):
        raise BusinessLinkageDataFlowError("步骤 order 不能重复。", "invalid_linkage")
    steps.sort(key=lambda item: item["order"])

    flow_entries: list[dict[str, Any]] = []
    dependency_ids: set[str] = set()
    for raw_dependency in raw_dependencies:
        if not isinstance(raw_dependency, Mapping):
            raise BusinessLinkageDataFlowError("依赖关系必须是对象。", "invalid_linkage")
        dependency_id = _required_text(raw_dependency.get("id"), "依赖 id", max_length=200)
        from_step_id = _required_text(raw_dependency.get("from_step_id"), "来源步骤 id", max_length=200)
        to_step_id = _required_text(raw_dependency.get("to_step_id"), "目标步骤 id", max_length=200)
        if dependency_id in dependency_ids or from_step_id == to_step_id:
            raise BusinessLinkageDataFlowError("依赖 id 不能重复，且来源和目标步骤不能相同。", "invalid_linkage")
        source_step = step_by_id.get(from_step_id)
        target_step = step_by_id.get(to_step_id)
        if source_step is None or target_step is None or source_step["order"] >= target_step["order"]:
            raise BusinessLinkageDataFlowError("依赖必须引用存在且按顺序排列的步骤。", "invalid_linkage")
        dependency_ids.add(dependency_id)
        mappings = raw_dependency.get("data_mappings")
        if not isinstance(mappings, list) or not mappings:
            raise BusinessLinkageDataFlowError(
                f"依赖 {dependency_id} 缺少明确的数据映射，不能安全设计数据流。",
                "missing_data_mapping",
            )
        if len(flow_entries) + len(mappings) > MAX_FLOW_MAPPINGS_PER_LINKAGE:
            raise BusinessLinkageDataFlowError("链路数据映射数量超过安全上限。", "input_too_large")
        for mapping_index, raw_mapping in enumerate(mappings, start=1):
            if not isinstance(raw_mapping, Mapping):
                raise BusinessLinkageDataFlowError("数据映射必须是对象。", "invalid_data_mapping")
            source_field = _required_text(
                raw_mapping.get("from") or raw_mapping.get("source_field"),
                "来源字段",
            )
            target_field = _required_text(
                raw_mapping.get("to") or raw_mapping.get("target_field"),
                "目标字段",
            )
            flow_entries.append(
                {
                    "id": f"{dependency_id}-flow-{mapping_index:03d}",
                    "dependency_id": dependency_id,
                    "from_step_id": from_step_id,
                    "to_step_id": to_step_id,
                    "source": {"step_id": from_step_id, "location": "response.body", "field": source_field},
                    "target": {"step_id": to_step_id, "location": _target_location(target_field), "field": target_field},
                    "transfer_type": _field_kind(source_field, target_field),
                    "operation": "extract_and_inject",
                    "required": True,
                }
            )
    return {"id": linkage_id, "name": name, "steps": steps, "flows": flow_entries}


def _assertions(linkage: Mapping[str, Any], flows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build one bounded status assertion per step plus data-presence checks."""
    step_assertions: list[dict[str, Any]] = []
    for step in linkage["steps"]:
        step_id = step["id"]
        step_assertions.append(
            {
                "id": f"{step_id}-status-2xx",
                "step_id": step_id,
                "kind": "status_code",
                "expression": "status_code >= 200 and status_code < 300",
                "severity": "high",
            }
        )
    seen_source_fields: set[tuple[str, str]] = set()
    for flow in flows:
        source = flow["source"]
        key = (str(source["step_id"]), str(source["field"]))
        if key in seen_source_fields:
            continue
        seen_source_fields.add(key)
        step_assertions.append(
            {
                "id": f"{source['step_id']}-data-{len(seen_source_fields):03d}",
                "step_id": source["step_id"],
                "kind": "required_output_field",
                "field": source["field"],
                "expression": f"response.body.{source['field']} is present and non-empty",
                "severity": "high",
            }
        )
    final_assertions = [
        {
            "id": f"{linkage['id']}-workflow-complete",
            "kind": "workflow_complete",
            "expression": "all steps passed in ascending order and every required data flow was injected",
            "severity": "high",
        }
    ]
    return step_assertions, final_assertions


def design_linkage_data_flow(
    linkages: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
) -> BusinessLinkageDataFlowResult:
    """Enrich T053 cases with explicit transfers and per-step/final assertions."""
    if isinstance(linkages, (str, bytes)) or not isinstance(linkages, Sequence) or not linkages:
        raise BusinessLinkageDataFlowError("业务链路必须是非空数组。", "empty_input")
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence) or not cases:
        raise BusinessLinkageDataFlowError("联调用例必须是非空数组。", "empty_input")

    normalized: dict[str, dict[str, Any]] = {}
    for raw_linkage in linkages:
        if not isinstance(raw_linkage, Mapping):
            raise BusinessLinkageDataFlowError("业务链路必须是对象。", "invalid_linkage")
        linkage = _normalize_linkage(raw_linkage)
        if linkage["id"] in normalized:
            raise BusinessLinkageDataFlowError("业务链路 id 不能重复。", "invalid_linkage")
        normalized[linkage["id"]] = linkage

    case_by_linkage: dict[str, Mapping[str, Any]] = {}
    for raw_case in cases:
        if not isinstance(raw_case, Mapping):
            raise BusinessLinkageDataFlowError("联调用例必须是对象。", "invalid_case")
        linkage_id = _required_text(raw_case.get("linkage_id") or raw_case.get("source_linkage_id"), "用例链路 id", max_length=200)
        if linkage_id in case_by_linkage or linkage_id not in normalized:
            raise BusinessLinkageDataFlowError("用例必须唯一引用已知业务链路。", "invalid_case")
        case_by_linkage[linkage_id] = raw_case
    if set(case_by_linkage) != set(normalized):
        raise BusinessLinkageDataFlowError("每条业务链路必须有对应的联调用例。", "invalid_case")

    enriched_cases: list[dict[str, Any]] = []
    total_flows = total_step_assertions = total_final_assertions = 0
    for linkage_id in sorted(normalized):
        linkage = normalized[linkage_id]
        flow_linkage = _normalize_linkage(linkages[next(index for index, item in enumerate(linkages) if str(item.get("id")) == linkage_id)])
        flows = flow_linkage["flows"]
        step_assertions, final_assertions = _assertions(flow_linkage, flows)
        source_case = case_by_linkage[linkage_id]
        enriched = dict(source_case)
        enriched.pop("automation_pending", None)
        enriched.update(
            {
                "data_flow": flows,
                "step_assertions": step_assertions,
                "final_assertions": final_assertions,
                "execution_design_status": "ready_for_t057_api_executor",
                "data_flow_status": "designed",
                "assertion_status": "designed",
                "expected_result": "所有接口按顺序完成，必要数据完成提取与注入，环节断言和最终业务结果断言全部通过。",
            }
        )
        enriched_cases.append(enriched)
        total_flows += len(flows)
        total_step_assertions += len(step_assertions)
        total_final_assertions += len(final_assertions)
    coverage_report = {
        "generation_method": "deterministic_linkage_data_flow_design",
        "execution_status": "designed_not_executed",
        "linkage_count": len(normalized),
        "case_count": len(enriched_cases),
        "data_flow_count": total_flows,
        "step_assertion_count": total_step_assertions,
        "final_assertion_count": total_final_assertions,
        "data_flow_status": "designed",
        "assertion_status": "designed",
        "execution_pending": "T057_api_executor",
    }
    return BusinessLinkageDataFlowResult(enriched_cases, coverage_report)


__all__ = [
    "BusinessLinkageDataFlowError",
    "BusinessLinkageDataFlowResult",
    "design_linkage_data_flow",
]
