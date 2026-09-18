"""Five-round test case generation with explicit execution evidence."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from core.task_state import CancelCheck, ProgressCallback, ensure_not_cancelled
from apps.case_generation.llm_adapter import CaseGenerationModelAdapter
from apps.case_generation.models import CaseGenerationRecord
from apps.case_generation.design_methods import (
    DESIGN_METHOD_LABELS,
    design_method_label,
    legacy_case_type,
    normalize_design_method,
    point_design_method,
)
from apps.configs.models import ModelRoutingPolicy
from apps.configs.routing import ModelRouteError, ModelRouteResolver
from apps.requirement_analysis.llm_adapter import ModelAnalysisError
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument
from apps.requirement_analysis.stability import analysis_review_state


class CaseGenerationError(ValueError):
    """Raised when an analysis cannot be converted to test cases safely."""


def _ensure_generation_ready(analysis: RequirementAnalysis) -> None:
    """Reject formal generation until analysis and manual review are both complete."""
    state = analysis_review_state(analysis.quality_status, analysis.coverage_report)
    if not state["analysis_complete"]:
        raise CaseGenerationError("当前需求分析尚未完成最终人工确认，不能进入正式用例生成；请完成审核清单并确认，或重新执行需求分析。")
    if not state["manual_review_complete"]:
        raise CaseGenerationError("需求分析已完成，但人工审核尚未完成；请在需求分析页完成全部审核并确认后再生成用例。")


@dataclass(frozen=True)
class CaseGenerationResult:
    """Final cases, coverage and a trace of the five generation rounds."""

    cases: list[dict[str, Any]]
    coverage_report: dict[str, Any]
    round_trace: list[dict[str, Any]]


def _analysis_payload(value: RequirementAnalysis | Mapping[str, Any]) -> Mapping[str, Any]:
    """Normalize a persisted analysis or a test payload."""
    if isinstance(value, RequirementAnalysis):
        return {
            "modules": value.modules,
            "functions": value.functions,
            "linkages": value.linkages,
            "test_points": value.test_points,
        }
    if not isinstance(value, Mapping):
        raise CaseGenerationError("需求分析结果格式无效。")
    return value


def _case(
    function: Mapping[str, Any],
    kind: str,
    round_added: int,
    *,
    linkage: Mapping[str, Any] | None = None,
    test_point: Mapping[str, Any] | None = None,
    variant: str = "",
    design_method: str | None = None,
) -> dict[str, Any]:
    """Build one safe, reviewable test case without executing a target system."""
    name = str(function.get("name") or function.get("description") or "未命名功能").strip()
    point_description = str((test_point or {}).get("description") or (test_point or {}).get("scenario") or "").strip()
    default_method = {
        "positive": "positive_flow",
        "negative": "error_guessing",
        "boundary": "boundary_value",
        "linkage": "linkage",
    }.get(kind, "positive_flow")
    method = normalize_design_method(
        design_method or (point_design_method(test_point) if test_point else default_method)
    )
    method_label = design_method_label(method)
    return {
        "id": "",
        "title": f"{point_description or name} - {method_label}{f' - {variant}' if variant else ''}",
        "type": kind,
        "test_design_method": method,
        "test_design_method_label": method_label,
        "priority": "P0" if kind in {"positive", "linkage"} else "P1",
        "source_function_id": function.get("id"),
        "source_module_id": function.get("module_id"),
        "source_test_point_id": (test_point or {}).get("id"),
        "evidence_ids": list((test_point or {}).get("evidence_ids") or []),
        "steps": [f"准备{function.get('module_id', '目标模块')}所需数据", f"执行{name}", *([f"验证{point_description}"] if point_description else [])],
        "expected_result": f"{point_description or name}符合需求并返回可验证结果",
        "automatable": kind != "linkage",
        "round_added": round_added,
        "linkage_id": linkage.get("id") if linkage else None,
    }


def _case_signature(item: Mapping[str, Any]) -> tuple[str, str, str, tuple[str, ...], str, str]:
    """Return a semantic signature that preserves distinct scenarios."""
    return (
        str(item.get("source_function_id", "")),
        str(item.get("type", "")),
        str(item.get("title", "")).strip().casefold(),
        tuple(str(step).strip().casefold() for step in item.get("steps", []) if str(step).strip()),
        str(item.get("expected_result", "")).strip().casefold(),
        str(item.get("linkage_id") or ""),
    )


def _case_deduplication_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return the stable business key used while merging five model rounds.

    A model may rephrase the same scenario on a later round.  Once a case is
    tied to an explicit test point, the test point and normalized design
    method are the durable identity; generated prose is not.  Results from
    legacy adapters that had their point ID inferred retain the old semantic
    signature so existing integrations can still return several scenarios.
    """
    source_test_point_id = str(item.get("source_test_point_id") or "").strip()
    if source_test_point_id and not item.get("_source_test_point_inferred"):
        method = normalize_design_method(
            item.get("test_design_method") or item.get("design_method") or item.get("type")
        )
        scenario_key = str(item.get("scenario_key") or "").strip().casefold()
        if scenario_key:
            return ("stable_test_point_method_scenario", source_test_point_id, method, scenario_key)
        # A point can legitimately have multiple scenarios under one method.
        # Without a model-provided stable scenario key, retain the old content
        # signature instead of collapsing valid coverage.
        return ("legacy_signature", *_case_signature(item))
    return ("legacy_signature", *_case_signature(item))


def _append_unique(cases: list[dict[str, Any]], additions: list[Mapping[str, Any]], round_number: int) -> int:
    """Append new cases by stable identity and annotate their generation round."""
    signatures = {_case_deduplication_key(item) for item in cases}
    added = 0
    for raw in additions:
        item = dict(raw)
        method = normalize_design_method(item.get("test_design_method") or item.get("design_method") or item.get("type"))
        item["test_design_method"] = method
        item["test_design_method_label"] = design_method_label(method)
        item["type"] = legacy_case_type(method, linkage=str(item.get("type")) == "linkage")
        item.setdefault("round_added", round_number)
        item.setdefault("id", "")
        item.setdefault("priority", "P0" if item.get("type") in {"positive", "linkage"} else "P1")
        item.setdefault("automatable", item.get("type") != "linkage")
        signature = _case_deduplication_key(item)
        if signature in signatures:
            continue
        signatures.add(signature)
        cases.append(item)
        added += 1
    return added


def _model_case_scope_guard(
    cases: list[Mapping[str, Any]],
    test_points: list[Mapping[str, Any]],
    coverage_plan: list[Mapping[str, Any]],
    existing_cases: list[Mapping[str, Any]],
    *,
    enforce_scope: bool,
) -> tuple[list[Mapping[str, Any]], dict[str, int]]:
    """Keep model output inside the selected points and a dynamic per-point budget.

    The model may return extra scenarios or accidentally reuse the whole analysis
    instead of the selected review scope. The backend is the final authority:
    cases without a selected test-point mapping are rejected, and each point gets
    one slot per required design dimension plus two additional scenario slots.
    This is intentionally dynamic rather than a fixed total-case cap.
    """
    if not enforce_scope:
        return cases, {
            "model_cases_rejected_out_of_scope": 0,
            "model_cases_rejected_over_limit": 0,
        }
    allowed_ids = {str(item.get("id")) for item in test_points if item.get("id")}
    required_methods = {
        str(entry.get("test_point_id")): len(entry.get("required_design_methods") or [])
        for entry in coverage_plan
        if entry.get("test_point_id")
    }
    limits = {
        point_id: max(3, method_count + 2)
        for point_id, method_count in required_methods.items()
    }
    counts = {
        point_id: sum(1 for item in existing_cases if str(item.get("source_test_point_id") or "") == point_id)
        for point_id in allowed_ids
    }
    accepted: list[Mapping[str, Any]] = []
    rejected_out_of_scope = 0
    rejected_over_limit = 0
    for raw in cases:
        if not isinstance(raw, Mapping):
            rejected_out_of_scope += 1
            continue
        item = dict(raw)
        point_id = str(item.get("source_test_point_id") or "")
        if point_id not in allowed_ids:
            rejected_out_of_scope += 1
            continue
        limit = limits.get(point_id, 3)
        if counts.get(point_id, 0) >= limit:
            rejected_over_limit += 1
            continue
        counts[point_id] = counts.get(point_id, 0) + 1
        accepted.append(item)
    return accepted, {
        "model_cases_rejected_out_of_scope": rejected_out_of_scope,
        "model_cases_rejected_over_limit": rejected_over_limit,
    }


def _trim_cases_to_scope_limits(
    cases: list[dict[str, Any]],
    test_points: list[Mapping[str, Any]],
    coverage_plan: list[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Apply the final per-point budget after model and baseline merging.

    Required design methods are retained first, then the remaining slots preserve
    the model's distinct scenarios.  This keeps coverage honest while preventing
    five model rounds plus a fallback pass from multiplying the same point.
    """
    allowed_ids = {str(item.get("id")) for item in test_points if item.get("id")}
    plan_by_point = {
        str(entry.get("test_point_id")): {
            "required": {normalize_design_method(value) for value in entry.get("required_design_methods", [])},
            "limit": max(3, len(entry.get("required_design_methods") or []) + 2),
        }
        for entry in coverage_plan
        if entry.get("test_point_id")
    }
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    unscoped: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(cases):
        point_id = str(item.get("source_test_point_id") or "")
        if point_id in allowed_ids:
            grouped.setdefault(point_id, []).append((index, item))
        else:
            unscoped.append((index, item))
    selected_indexes: set[int] = set()
    trimmed = len(unscoped)
    for point_id, entries in grouped.items():
        plan = plan_by_point.get(point_id, {"required": set(), "limit": 3})
        required = set(plan["required"])
        limit = int(plan["limit"])
        chosen: list[tuple[int, dict[str, Any]]] = []
        chosen_indexes: set[int] = set()
        for method in sorted(required):
            match = next(
                (
                    entry for entry in entries
                    if entry[0] not in chosen_indexes
                    and normalize_design_method(entry[1].get("test_design_method") or entry[1].get("type")) == method
                ),
                None,
            )
            if match is not None:
                chosen.append(match)
                chosen_indexes.add(match[0])
        for entry in entries:
            if len(chosen) >= limit:
                break
            if entry[0] not in chosen_indexes:
                chosen.append(entry)
                chosen_indexes.add(entry[0])
        selected_indexes.update(index for index, _ in chosen)
        trimmed += max(0, len(entries) - len(chosen))
    return [item for index, item in enumerate(cases) if index in selected_indexes], trimmed


def _deterministic_round(
    functions: list[Mapping[str, Any]],
    linkages: list[Mapping[str, Any]],
    round_number: int,
    test_points: list[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Create a bounded fallback increment from test points for one coverage dimension."""
    if test_points:
        function_by_id = {str(item.get("id")): item for item in functions}
        linkage_by_id = {str(item.get("id")): item for item in linkages}
        candidates: list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None]] = []
        for point in test_points:
            function_id = str(point.get("function_id") or point.get("source_function_id") or "")
            linkage = linkage_by_id.get(str(point.get("scenario_id") or point.get("linkage_id") or ""))
            if not function_id and linkage:
                function_id = str(linkage.get("from") or "")
            function = function_by_id.get(function_id)
            if function:
                candidates.append((point, function, linkage))

        # A selected point is the approved generation scope, not a request to
        # generate only one legacy category.  The fallback therefore covers
        # every selected point through the five explicit design dimensions.
        round_methods = {
            1: ("positive", "equivalence_class"),
            2: ("negative", "error_guessing"),
            3: ("boundary", "boundary_value"),
            4: ("linkage", "cause_effect_graph"),
            5: ("boundary", "state_transition"),
        }

        selected = candidates
        fallback_kind, fallback_method = round_methods[round_number]
        result = [
            _case(
                function,
                fallback_kind,
                round_number,
                test_point=point,
                linkage=linkage,
                variant="回归与兼容" if round_number == 5 else "",
                design_method=fallback_method,
            )
            for point, function, linkage in selected
        ]
        if round_number == 4 and not result:
            for linkage in linkages:
                source = function_by_id.get(str(linkage.get("from")))
                if source:
                    result.append(_case(source, "linkage", 4, linkage=linkage, design_method="cause_effect_graph"))
        return result
    if round_number == 1:
        return [_case(function, "positive", 1) for function in functions]
    if round_number == 2:
        return [_case(function, "negative", 2) for function in functions]
    if round_number == 3:
        return [_case(function, "boundary", 3) for function in functions]
    if round_number == 4:
        result: list[dict[str, Any]] = []
        by_id = {str(item.get("id")): item for item in functions}
        for linkage in linkages:
            source = by_id.get(str(linkage.get("from"))) or by_id.get(str(linkage.get("source_function_id")))
            if source:
                result.append(_case(source, "linkage", 4, linkage=linkage))
        return result
    return [_case(function, "positive", 5, variant="回归与兼容") for function in functions]


def _annotate_model_cases(
    cases: Any,
    test_points: list[Mapping[str, Any]],
    linkages: list[Mapping[str, Any]] | None = None,
) -> list[Mapping[str, Any]]:
    """Attach compatible test-point IDs to legacy model cases when omitted."""
    if not isinstance(cases, list) or not test_points:
        return cases if isinstance(cases, list) else []
    linkage_by_id = {str(item.get("id")): item for item in (linkages or [])}
    by_key: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for point in test_points:
        function_id = str(point.get("function_id") or point.get("source_function_id") or "")
        if not function_id:
            linkage = linkage_by_id.get(str(point.get("scenario_id") or point.get("linkage_id") or ""))
            function_id = str((linkage or {}).get("from") or "")
        kind = str(point.get("type") or "positive").casefold()
        normalized = legacy_case_type(point_design_method(point), linkage=False)
        by_key.setdefault((function_id, normalized), []).append(point)
    offsets: dict[tuple[str, str], int] = {}
    normalized_cases: list[Mapping[str, Any]] = []
    for raw in cases:
        if not isinstance(raw, Mapping):
            normalized_cases.append(raw)
            continue
        item = dict(raw)
        if not item.get("source_test_point_id"):
            key = (str(item.get("source_function_id") or ""), str(item.get("type") or "positive"))
            points = by_key.get(key, [])
            if points:
                index = offsets.get(key, 0)
                item["source_test_point_id"] = points[min(index, len(points) - 1)].get("id")
                item["_source_test_point_inferred"] = True
                offsets[key] = index + 1
        method = normalize_design_method(item.get("test_design_method") or item.get("design_method") or item.get("type"))
        item["test_design_method"] = method
        item["test_design_method_label"] = design_method_label(method)
        normalized_cases.append(item)
    return normalized_cases


def _model_failure(exc: ModelAnalysisError, round_number: int) -> dict[str, Any]:
    """Build safe round failure evidence without provider credentials or raw input."""
    return {
        "round": round_number,
        "status": "failed",
        "error_code": getattr(exc, "code", "model_error"),
        "structured_generation": {
            "status": "partial" if getattr(exc, "structured_trace", ()) else "failed",
            "segments": [dict(item) for item in getattr(exc, "structured_trace", ())],
        },
    }


def _design_method_baseline(
    functions: list[Mapping[str, Any]],
    linkages: list[Mapping[str, Any]],
    test_points: list[Mapping[str, Any]],
    existing_cases: list[Mapping[str, Any]],
    coverage_plan: list[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return only the dynamically required method cases missing from model output."""
    existing = {
        (str(item.get("source_test_point_id")), str(item.get("test_design_method")))
        for item in existing_cases
        if item.get("source_test_point_id") and item.get("test_design_method")
    }
    function_by_id = {str(item.get("id")): item for item in functions}
    linkage_by_id = {str(item.get("id")): item for item in linkages}
    points_by_id = {str(item.get("id")): item for item in test_points}
    additions: list[dict[str, Any]] = []
    plan = coverage_plan or _build_coverage_plan(test_points, linkages)
    for entry in plan:
        point_id = str(entry.get("test_point_id") or "")
        point = points_by_id.get(point_id)
        if not point:
            continue
        function_id = str(point.get("function_id") or point.get("source_function_id") or "")
        linkage = linkage_by_id.get(str(point.get("scenario_id") or point.get("linkage_id") or ""))
        if not function_id and linkage:
            function_id = str(linkage.get("from") or "")
        function = function_by_id.get(function_id)
        if not function:
            continue
        for method in entry.get("required_design_methods", []):
            normalized_method = normalize_design_method(method)
            key = (point_id, normalized_method)
            if key in existing:
                continue
            existing.add(key)
            kind = legacy_case_type(normalized_method, linkage=normalized_method == "linkage")
            additions.append(
                _case(
                    function,
                    kind,
                    5,
                    linkage=linkage,
                    test_point=point,
                    design_method=normalized_method,
                )
            )
    return additions


def _build_coverage_plan(
    test_points: list[Mapping[str, Any]],
    linkages: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Derive coverage dimensions from each point without imposing a case-count cap.

    The plan is a minimum coverage contract.  The model may add any number of
    distinct scenarios when the requirement justifies them; the generator only
    fills dimensions that are still missing after model rounds.
    """
    keyword_methods = (
        (("边界", "上限", "下限", "长度", "范围", "金额", "数量", "阈值", "limit", "boundary"), "boundary_value"),
        (("状态", "转场", "切换", "恢复", "重试", "spin", "state", "transition"), "state_transition"),
        (("权限", "认证", "未授权", "越权", "安全", "token", "permission", "security"), "security"),
        (("性能", "并发", "响应时间", "吞吐", "performance", "concurrency"), "performance"),
        (("联动", "跨模块", "接口链路", "上下游", "cause", "linkage"), "cause_effect_graph"),
        (("回归", "兼容", "历史数据", "版本", "regression", "compatibility"), "regression_compatibility"),
    )
    linkage_ids = {
        str(item.get("id"))
        for item in linkages
        if isinstance(item, Mapping) and item.get("id")
    }
    plan: list[dict[str, Any]] = []
    for point in test_points:
        point_id = str(point.get("id") or "")
        if not point_id:
            continue
        raw_type = str(point.get("type") or "").strip().casefold()
        explicit_method = str(point.get("test_design_method") or point.get("design_method") or "").strip()
        if explicit_method:
            methods = {normalize_design_method(explicit_method)}
        elif raw_type == "positive":
            methods = {"positive_flow", "equivalence_class"}
        elif raw_type == "negative":
            methods = {"error_guessing"}
        elif raw_type == "boundary":
            methods = {"boundary_value", "equivalence_class"}
        elif raw_type == "security":
            methods = {"security", "error_guessing"}
        elif raw_type == "performance":
            methods = {"performance"}
        elif raw_type == "linkage":
            methods = {"linkage", "cause_effect_graph"}
        else:
            # Legacy points without a type retain the five-dimensional
            # deterministic baseline for compatibility.
            methods = {"equivalence_class", "error_guessing", "boundary_value", "cause_effect_graph", "state_transition"}
        description = " ".join(
            str(point.get(field) or "") for field in ("description", "scenario", "acceptance_criteria")
        ).casefold()
        for keywords, method in keyword_methods:
            if any(keyword.casefold() in description for keyword in keywords):
                methods.add(method)
        scenario_id = str(point.get("scenario_id") or point.get("linkage_id") or "")
        if scenario_id in linkage_ids:
            methods.update({"linkage", "cause_effect_graph"})
        plan.append({
            "test_point_id": point_id,
            "required_design_methods": sorted(methods),
        })
    return plan


def _coverage_metric(total_ids: set[str], covered_ids: set[str]) -> dict[str, Any]:
    """Build one comparable coverage metric with explicit unavailable semantics."""
    total = {str(value) for value in total_ids if str(value)}
    covered = total & {str(value) for value in covered_ids if str(value)}
    return {
        "rate": round(len(covered) / len(total), 4) if total else None,
        "covered_count": len(covered),
        "total_count": len(total),
        "covered_ids": sorted(covered),
        "uncovered_ids": sorted(total - covered),
        "status": "available" if total else "unavailable",
    }


def _build_coverage_metrics(
    *,
    modules: list[Mapping[str, Any]],
    functions: list[Mapping[str, Any]],
    linkages: list[Mapping[str, Any]],
    test_points: list[Mapping[str, Any]],
    coverage_plan: list[Mapping[str, Any]],
    cases: list[Mapping[str, Any]],
    evidence: list[Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Calculate the four canonical coverage rates from one source of truth."""
    evidence_ids = {
        str(item.get("id"))
        for item in (evidence or [])
        if isinstance(item, Mapping) and item.get("id")
    }
    cited_evidence_ids: set[str] = set()
    for collection in (modules, functions, linkages, test_points):
        for item in collection:
            if isinstance(item, Mapping) and isinstance(item.get("evidence_ids"), list):
                cited_evidence_ids.update(str(value) for value in item["evidence_ids"] if value)
    function_ids = {
        str(item.get("id"))
        for item in functions
        if isinstance(item, Mapping) and item.get("id")
    }
    covered_function_ids = {
        str(item.get("source_function_id"))
        for item in cases
        if isinstance(item, Mapping) and item.get("source_function_id")
    }
    dimension_ids: set[str] = set()
    for entry in coverage_plan:
        point_id = str(entry.get("test_point_id") or "")
        dimension_ids.update(
            f"{point_id}:{normalize_design_method(method)}"
            for method in entry.get("required_design_methods", [])
            if point_id and method
        )
    covered_dimension_ids = {
        f"{str(item.get('source_test_point_id'))}:{normalize_design_method(item.get('test_design_method') or item.get('type'))}"
        for item in cases
        if isinstance(item, Mapping) and item.get("source_test_point_id") and item.get("test_design_method")
    }
    linkage_ids = {
        str(item.get("id"))
        for item in linkages
        if isinstance(item, Mapping) and item.get("id")
    }
    point_linkages = {
        str(item.get("id")): str(item.get("scenario_id") or item.get("linkage_id"))
        for item in test_points
        if isinstance(item, Mapping)
        and item.get("id")
        and (item.get("scenario_id") or item.get("linkage_id"))
    }
    covered_linkage_ids = {
        str(item.get("linkage_id") or point_linkages.get(str(item.get("source_test_point_id"))))
        for item in cases
        if isinstance(item, Mapping)
        and (item.get("linkage_id") or point_linkages.get(str(item.get("source_test_point_id"))))
    }
    return {
        "evidence": _coverage_metric(evidence_ids, cited_evidence_ids),
        "function": _coverage_metric(function_ids, covered_function_ids),
        "test_dimension": _coverage_metric(dimension_ids, covered_dimension_ids),
        "linkage": _coverage_metric(linkage_ids, covered_linkage_ids),
    }


def generate_cases(
    analysis: RequirementAnalysis | Mapping[str, Any],
    *,
    model_adapter: CaseGenerationModelAdapter | None = None,
    evidence: list[dict[str, Any]] | None = None,
    project_name: str | None = None,
    document_text: str = "",
    preferred_model_name: str | None = None,
    allow_deterministic_baseline: bool = True,
    route_metadata: Mapping[str, Any] | None = None,
    test_point_ids: list[str] | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> CaseGenerationResult:
    """Run five cumulative coverage passes with explicit model/fallback status."""
    payload = _analysis_payload(analysis)
    modules = payload.get("modules") if isinstance(payload.get("modules"), list) else []
    functions = payload.get("functions")
    test_points = payload.get("test_points") if isinstance(payload.get("test_points"), list) else []
    linkages = payload.get("linkages") if isinstance(payload.get("linkages"), list) else []
    if test_point_ids is not None:
        selected_ids = {str(value) for value in test_point_ids}
        test_points = [item for item in test_points if isinstance(item, Mapping) and str(item.get("id")) in selected_ids]
        if not test_points:
            raise CaseGenerationError("没有已审核的测试点可生成用例。")
    if not isinstance(functions, list) or not functions:
        raise CaseGenerationError("需求分析结果没有可生成用例的功能点。")
    functions = [item for item in functions if isinstance(item, Mapping) and item.get("id")]
    if not functions:
        raise CaseGenerationError("功能点缺少有效标识。")
    if test_point_ids is not None:
        linkage_by_id = {
            str(item.get("id")): item
            for item in linkages
            if isinstance(item, Mapping) and item.get("id")
        }
        selected_function_ids = {
            str(item.get("function_id") or item.get("source_function_id"))
            for item in test_points
            if item.get("function_id") or item.get("source_function_id")
        }
        selected_linkage_ids = {
            str(item.get("scenario_id") or item.get("linkage_id"))
            for item in test_points
            if item.get("scenario_id") or item.get("linkage_id")
        }
        for linkage_id in selected_linkage_ids:
            linkage = linkage_by_id.get(linkage_id)
            if linkage:
                selected_function_ids.update(
                    str(linkage.get(field))
                    for field in ("from", "to", "source_function_id", "target_function_id")
                    if linkage.get(field)
                )
        functions = [item for item in functions if str(item.get("id")) in selected_function_ids]
        linkages = [
            item for item in linkages
            if str(item.get("id")) in selected_linkage_ids
            or str(item.get("from")) in selected_function_ids
            or str(item.get("to")) in selected_function_ids
            or str(item.get("source_function_id")) in selected_function_ids
            or str(item.get("target_function_id")) in selected_function_ids
        ]
        if not functions:
            raise CaseGenerationError("已审核测试点未关联可生成用例的功能点。")
    if test_points and not any(isinstance(item, Mapping) and item.get("id") for item in test_points):
        raise CaseGenerationError("测试点缺少有效标识。")
    if test_points:
        function_ids = {str(item.get("id")) for item in functions}
        linkage_ids = {str(item.get("id")): item for item in linkages if isinstance(item, Mapping) and item.get("id")}
        for point in test_points:
            if not isinstance(point, Mapping) or not point.get("id"):
                raise CaseGenerationError("测试点缺少有效标识。")
            function_id = str(point.get("function_id") or point.get("source_function_id") or "")
            linkage = linkage_ids.get(str(point.get("scenario_id") or point.get("linkage_id") or ""))
            if not function_id and linkage:
                function_id = str(linkage.get("from") or "")
            if function_id not in function_ids:
                raise CaseGenerationError(f"测试点 {point.get('id')} 未关联有效功能点。")

    coverage_plan = _build_coverage_plan(test_points, linkages)
    cases: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    model_rounds: list[int] = []
    model_warnings: list[str] = []
    model_failures: list[dict[str, Any]] = []
    fallback_used = False
    scope_trimmed = 0
    use_incremental_model = bool(
        model_adapter
        and model_adapter.__class__.__module__ == "apps.case_generation.llm_adapter"
        and model_adapter.__class__.__name__ == "CaseGenerationModelAdapter"
    )

    for round_number in range(1, 6):
        ensure_not_cancelled(cancel_check)
        if progress_callback:
            progress_callback({
                "status": "running",
                "current_step": f"用例生成·第{round_number}轮",
                "current_round": round_number,
                "total_rounds": 5,
                "completed_rounds": round_number - 1,
            })
        before = len(cases)
        stage = "deterministic_baseline"
        note = "确定性覆盖基线（未配置模型）"
        round_analysis: dict[str, Any] = {}
        model_result: dict[str, Any] = {}
        failure: dict[str, Any] | None = None
        if use_incremental_model and model_adapter:
            stage = "model_incremental"
            note = "模型基于需求分析、测试点和已有用例递进补充本轮覆盖"
            try:
                model_result = model_adapter.generate_round(
                    round_number=round_number,
                    document_text=document_text,
                    modules=modules,
                    functions=functions,
                    test_points=test_points,
                    coverage_plan=coverage_plan,
                    linkages=linkages,
                    existing_cases=cases,
                    evidence=evidence or [],
                    project_name=project_name,
                    preferred_model_name=preferred_model_name,
                )
                round_analysis = model_result.get("round_analysis", {}) if isinstance(model_result.get("round_analysis"), dict) else {}
                model_rounds.append(round_number)
            except ModelAnalysisError as exc:
                failure = _model_failure(exc, round_number)
                model_failures.append(failure)
                if not allow_deterministic_baseline:
                    error = CaseGenerationError(f"第{round_number}轮模型调用失败，未生成确定性替代结果：{exc}")
                    error.partial_cases = list(cases)
                    error.partial_round_trace = [
                        *trace,
                        {**failure, "stage": "model_failed", "added": 0, "total": len(cases)},
                    ]
                    error.structured_trace = list(exc.structured_trace)
                    raise error from exc
                fallback_used = True
                model_warnings.append(f"第{round_number}轮：{exc}")
                stage = "deterministic_fallback"
                note = "模型本轮失败，使用确定性覆盖补充"
        elif round_number == 1 and model_adapter:
            # Backward-compatible single-pass fakes remain supported in tests and integrations.
            stage = "model_incremental"
            note = "兼容单次模型适配器"
            try:
                model_result = model_adapter.generate(
                    functions=functions,
                    linkages=linkages,
                    evidence=evidence or [],
                    project_name=project_name,
                )
                round_analysis = model_result.get("round_analysis", {}) if isinstance(model_result.get("round_analysis"), dict) else {}
                model_rounds.append(1)
            except ModelAnalysisError as exc:
                failure = _model_failure(exc, 1)
                model_failures.append(failure)
                if not allow_deterministic_baseline:
                    error = CaseGenerationError(f"第1轮模型调用失败，未生成确定性替代结果：{exc}")
                    error.partial_cases = list(cases)
                    error.partial_round_trace = [{**failure, "stage": "model_failed", "added": 0, "total": len(cases)}]
                    error.structured_trace = list(exc.structured_trace)
                    raise error from exc
                fallback_used = True
                model_warnings.append(f"第1轮：{exc}")
                stage = "deterministic_fallback"
                note = "模型失败，使用确定性覆盖补充"

        if stage in {"model_incremental"} and model_result:
            model_cases = _annotate_model_cases(model_result.get("cases", []), test_points, linkages)
            model_cases, scope_stats = _model_case_scope_guard(
                model_cases,
                test_points,
                coverage_plan,
                cases,
                enforce_scope=test_point_ids is not None,
            )
            added = _append_unique(cases, model_cases, round_number)
        else:
            scope_stats = {"model_cases_rejected_out_of_scope": 0, "model_cases_rejected_over_limit": 0}
            added = _append_unique(cases, _deterministic_round(functions, linkages, round_number, test_points), round_number)
        round_entry: dict[str, Any] = {
            "round": round_number,
            "stage": stage,
            "status": "completed",
            "model_status": "failed" if failure else ("completed" if stage == "model_incremental" else "not_configured"),
            "added": added,
            "total": len(cases),
            "note": note,
            "analysis": round_analysis,
            "scope_guard": scope_stats,
        }
        if failure:
            round_entry["model_error_code"] = failure["error_code"]
        coverage_result = model_result.get("coverage_report") if isinstance(model_result, dict) else None
        if isinstance(coverage_result, dict):
            if isinstance(coverage_result.get("structured_generation"), dict):
                round_entry["structured_generation"] = coverage_result["structured_generation"]
            if isinstance(coverage_result.get("model_route"), dict):
                round_entry["model_route"] = coverage_result["model_route"]
        trace.append(round_entry)
        if progress_callback:
            progress_callback({
                "status": "running",
                "current_step": f"用例生成·第{round_number}轮已完成",
                "current_round": round_number,
                "total_rounds": 5,
                "completed_rounds": round_number,
                "round": dict(round_entry),
            })

    if test_points and cases and (not model_rounds or use_incremental_model) and all(
        item.get("source_test_point_id") and not item.get("_source_test_point_inferred")
        for item in cases
    ):
        method_additions = _design_method_baseline(functions, linkages, test_points, cases, coverage_plan)
        if method_additions:
            added = _append_unique(cases, method_additions, 5)
            if model_rounds:
                fallback_used = True
                model_warnings.append("模型结果未覆盖动态覆盖计划中的测试设计方法，已补充确定性基线")
            if trace:
                trace[-1]["added"] = int(trace[-1].get("added", 0)) + added
                trace[-1]["total"] = len(cases)
                trace[-1]["note"] = f"{trace[-1].get('note', '')}；补充缺失测试设计方法"

    if test_point_ids is not None:
        cases, scope_trimmed = _trim_cases_to_scope_limits(cases, test_points, coverage_plan)
        if trace and scope_trimmed:
            trace[-1].setdefault("scope_guard", {})["cases_trimmed_to_scope_limit"] = scope_trimmed

    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in cases:
        deduplication_key = _case_deduplication_key(item)
        item.pop("_source_test_point_inferred", None)
        item["steps"] = [str(step).strip() for step in item.get("steps", []) if str(step).strip()]
        item["expected_result"] = str(item.get("expected_result") or "结果可验证").strip()
        method = normalize_design_method(item.get("test_design_method") or item.get("design_method") or item.get("type"))
        item["test_design_method"] = method
        item["test_design_method_label"] = design_method_label(method)
        unique.setdefault(deduplication_key, item)
    cases = list(unique.values())
    cases.sort(key=lambda item: (str(item.get("source_function_id")), str(item.get("type"))))
    for index, item in enumerate(cases, start=1):
        item["id"] = f"case-{index:03d}"
    types = {kind: sum(item["type"] == kind for item in cases) for kind in ("positive", "negative", "boundary", "linkage")}
    design_methods = {
        method: sum(item.get("test_design_method") == method for item in cases)
        for method in DESIGN_METHOD_LABELS
        if any(item.get("test_design_method") == method for item in cases)
    }
    covered_test_point_ids = sorted({str(item.get("source_test_point_id")) for item in cases if item.get("source_test_point_id")})
    covered_point_set = set(covered_test_point_ids)
    coverage_gaps: list[dict[str, Any]] = []
    planned_dimension_count = 0
    covered_dimension_count = 0
    for entry in coverage_plan:
        point_id = str(entry.get("test_point_id") or "")
        required_methods = {normalize_design_method(value) for value in entry.get("required_design_methods", [])}
        covered_methods = {
            normalize_design_method(item.get("test_design_method") or item.get("type"))
            for item in cases
            if str(item.get("source_test_point_id") or "") == point_id
        }
        missing_methods = sorted(required_methods - covered_methods)
        planned_dimension_count += len(required_methods)
        covered_dimension_count += len(required_methods & covered_methods)
        if point_id not in covered_point_set or missing_methods:
            coverage_gaps.append({
                "test_point_id": point_id,
                "required_design_methods": sorted(required_methods),
                "covered_design_methods": sorted(required_methods & covered_methods),
                "missing_design_methods": missing_methods,
            })
    model_verified = (model_rounds == [1, 2, 3, 4, 5] or (model_rounds == [1] and not use_incremental_model)) and not fallback_used
    method = "model_verified" if model_verified else ("deterministic_fallback" if fallback_used else ("model_partial" if model_rounds else "deterministic_baseline"))
    coverage_metrics = _build_coverage_metrics(
        modules=modules,
        functions=functions,
        linkages=linkages,
        test_points=test_points,
        coverage_plan=coverage_plan,
        cases=cases,
        evidence=evidence,
    )
    coverage: dict[str, Any] = {
        "module_count": len(modules),
        "function_count": len(functions),
        "test_point_count": len(test_points),
        "linkage_count": len(linkages),
        "case_count": len(cases),
        "deduplication": {
            "strategy": "source_test_point_id + test_design_method + scenario_key",
            "legacy_fallback": "semantic_case_signature_when_scenario_key_is_missing_or_source_test_point_id_was_inferred",
        },
        "types": types,
        "design_methods": design_methods,
        "coverage_plan": coverage_plan,
        "coverage_gaps": coverage_gaps,
        "coverage_metric_version": "requirement-case-coverage-v1",
        "coverage_metrics": coverage_metrics,
        "evidence_coverage_rate": coverage_metrics["evidence"]["rate"],
        "function_coverage_rate": coverage_metrics["function"]["rate"],
        "test_dimension_coverage_rate": coverage_metrics["test_dimension"]["rate"],
        "linkage_coverage_rate": coverage_metrics["linkage"]["rate"],
        "design_dimension_coverage_rate": round(covered_dimension_count / planned_dimension_count, 4) if planned_dimension_count else None,
        "covered_function_ids": sorted({str(item["source_function_id"]) for item in cases}),
        "covered_test_point_ids": covered_test_point_ids,
        "test_point_coverage_rate": round(
            len({str(item.get("source_test_point_id")) for item in cases if item.get("source_test_point_id")}) / len(test_points), 4
        ) if test_points else None,
        "coverage_rate": round(
            len({str(item.get("source_test_point_id")) for item in cases if item.get("source_test_point_id")}) / len(test_points), 4
        ) if test_points else round(len({str(item["source_function_id"]) for item in cases}) / len(functions), 4),
        "analysis_method": method,
        "execution_status": "completed",
        "model_rounds": model_rounds,
        "model_round_statuses": [
            *[{"round": item, "status": "completed"} for item in model_rounds],
            *[{"round": item["round"], "status": "failed", "error_code": item["error_code"]} for item in model_failures],
        ],
        "round_trace": trace,
        "scope_guard": {
            "selected_test_point_ids": sorted({str(item.get("id")) for item in test_points if item.get("id")}),
            "per_test_point_case_limits": {
                str(entry.get("test_point_id")): max(3, len(entry.get("required_design_methods") or []) + 2)
                for entry in coverage_plan
                if entry.get("test_point_id")
            },
            "model_cases_rejected_out_of_scope": sum(
                int(item.get("scope_guard", {}).get("model_cases_rejected_out_of_scope", 0)) for item in trace
            ),
            "model_cases_rejected_over_limit": sum(
                int(item.get("scope_guard", {}).get("model_cases_rejected_over_limit", 0)) for item in trace
            ),
            "cases_trimmed_to_scope_limit": scope_trimmed,
        },
    }
    if route_metadata:
        coverage["model_route_resolution"] = dict(route_metadata)
    if model_warnings:
        coverage["model_warning"] = "；".join(model_warnings)
    return CaseGenerationResult(cases, coverage, trace)


def create_pending_generation_record(
    document: RequirementDocument,
    analysis: RequirementAnalysis | None = None,
    reviewed_test_point_ids: list[str] | None = None,
) -> CaseGenerationRecord:
    """Validate scope and create a visible generation record before queueing work."""
    source = analysis or document.analyses.order_by("-created_at").first()
    if source is None:
        raise CaseGenerationError("需求文档尚未完成需求分析。")
    _ensure_generation_ready(source)
    report = dict(source.coverage_report or {})
    confirmation = report.get("manual_confirmation") if isinstance(report.get("manual_confirmation"), dict) else {}
    approved_ids = {str(value) for value in confirmation.get("reviewed_test_point_ids", []) if value}
    if source.quality_status == RequirementAnalysis.QualityStatus.COMPLETE and not approved_ids:
        approved_ids = {str(item.get("id")) for item in (source.test_points or []) if isinstance(item, Mapping) and item.get("id")}
    selected_ids = approved_ids if reviewed_test_point_ids is None else {str(value) for value in reviewed_test_point_ids if value}
    if source.quality_status != RequirementAnalysis.QualityStatus.COMPLETE and not selected_ids:
        raise CaseGenerationError("当前需求分析仍待审核，请先标记至少一个已审核测试点。")
    if selected_ids is not None and not selected_ids.issubset(approved_ids):
        raise CaseGenerationError("只能为已审核测试点生成用例，请先在需求分析页标记审核结果。")
    return CaseGenerationRecord.objects.create(
        project=document.project,
        document=document,
        coverage_report={
            "generation_status": "generating",
            "execution_status": "running",
            "reviewed_test_point_ids": sorted(selected_ids),
        },
        status=CaseGenerationRecord.Status.GENERATING,
    )


def generate_document_cases(
    document: RequirementDocument,
    analysis: RequirementAnalysis | None = None,
    *,
    preferred_model_name: str | None = None,
    reviewed_test_point_ids: list[str] | None = None,
    record: CaseGenerationRecord | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> CaseGenerationRecord:
    """Persist one five-round generation run for a project requirement document."""
    source = analysis or document.analyses.order_by("-created_at").first()
    if source is None:
        raise CaseGenerationError("需求文档尚未完成需求分析。")
    _ensure_generation_ready(source)
    if record is None:
        record = create_pending_generation_record(document, source, reviewed_test_point_ids)
    report = dict(record.coverage_report or {})
    selected_ids = {str(value) for value in report.get("reviewed_test_point_ids", []) if value}
    if reviewed_test_point_ids is not None:
        selected_ids = {str(value) for value in reviewed_test_point_ids if value}
    route = None
    try:
        try:
            route = ModelRouteResolver().resolve(
                ModelRoutingPolicy.FeatureKey.CASE_GENERATION,
                preferred_name=preferred_model_name,
            )
        except ModelRouteError as exc:
            raise CaseGenerationError(f"用例生成模型路由不可用：{exc}") from exc
        has_compatible_model = route.available
        model_adapter = CaseGenerationModelAdapter() if has_compatible_model else None
        result = generate_cases(
            source,
            model_adapter=model_adapter,
            evidence=document.parse_evidence,
            project_name=document.project.name,
            document_text=document.content_text,
            preferred_model_name=preferred_model_name,
            # A configured provider is preferred, but a provider error must
            # not discard the reviewed scope.  The record will be explicitly
            # marked deterministic_fallback with round-level model errors.
            allow_deterministic_baseline=True,
            route_metadata=route.as_dict(),
            test_point_ids=sorted(selected_ids) if selected_ids is not None else None,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        record.rounds = 5
        record.total_cases = len(result.cases)
        record.auto_cases = sum(1 for item in result.cases if item["automatable"])
        record.manual_cases = record.total_cases - record.auto_cases
        record.cases = result.cases
        record.coverage_report = {
            **result.coverage_report,
            "round_trace": result.round_trace,
            "reviewed_test_point_ids": sorted(selected_ids) if selected_ids is not None else [],
        }
        record.status = CaseGenerationRecord.Status.COMPLETED
        record.save(update_fields=("rounds", "total_cases", "auto_cases", "manual_cases", "cases", "coverage_report", "status"))
    except CaseGenerationError as exc:
        partial_cases = getattr(exc, "partial_cases", None)
        partial_trace = getattr(exc, "partial_round_trace", [])
        route_report = route.as_dict() if route else {}
        if isinstance(partial_cases, list) and partial_cases:
            record.cases = partial_cases
            record.total_cases = len(partial_cases)
            record.auto_cases = sum(1 for item in partial_cases if item.get("automatable"))
            record.manual_cases = record.total_cases - record.auto_cases
            record.rounds = len(partial_trace)
            record.coverage_report = {
                "analysis_method": "model_partial",
                "generation_status": "partial",
                "execution_status": "failed",
                "partial_result": True,
                "round_trace": partial_trace,
                "model_route_resolution": route_report,
                "structured_generation": {"status": "partial", "segments": getattr(exc, "structured_trace", [])},
            }
            record.save(update_fields=("rounds", "total_cases", "auto_cases", "manual_cases", "cases", "coverage_report", "status"))
        else:
            record.rounds = len(partial_trace) if isinstance(partial_trace, list) else 0
            record.coverage_report = {
                "analysis_method": "failed",
                "generation_status": "failed",
                "execution_status": "failed",
                "round_trace": partial_trace if isinstance(partial_trace, list) else [],
                "model_route_resolution": route_report,
            }
            record.save(update_fields=("rounds", "coverage_report", "status"))
        record.status = CaseGenerationRecord.Status.FAILED
        record.save(update_fields=("status",))
        raise
    return record


__all__ = ["CaseGenerationError", "CaseGenerationResult", "create_pending_generation_record", "generate_cases", "generate_document_cases"]
