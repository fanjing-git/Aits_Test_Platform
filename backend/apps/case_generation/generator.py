"""Five-round test case generation with explicit execution evidence."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from apps.case_generation.llm_adapter import CaseGenerationModelAdapter
from apps.case_generation.models import CaseGenerationRecord
from apps.configs.models import ModelRoutingPolicy
from apps.configs.routing import ModelRouteError, ModelRouteResolver
from apps.requirement_analysis.llm_adapter import ModelAnalysisError
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument


class CaseGenerationError(ValueError):
    """Raised when an analysis cannot be converted to test cases safely."""


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
) -> dict[str, Any]:
    """Build one safe, reviewable test case without executing a target system."""
    name = str(function.get("name") or function.get("description") or "未命名功能").strip()
    point_description = str((test_point or {}).get("description") or (test_point or {}).get("scenario") or "").strip()
    labels = {
        "positive": "正常流程",
        "negative": "异常与权限",
        "boundary": "边界条件",
        "linkage": "跨模块联动",
    }
    return {
        "id": "",
        "title": f"{point_description or name} - {labels[kind]}{f' - {variant}' if variant else ''}",
        "type": kind,
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


def _append_unique(cases: list[dict[str, Any]], additions: list[Mapping[str, Any]], round_number: int) -> int:
    """Append only new scenario signatures and annotate their generation round."""
    signatures = {_case_signature(item) for item in cases}
    added = 0
    for raw in additions:
        item = dict(raw)
        item.setdefault("round_added", round_number)
        item.setdefault("id", "")
        item.setdefault("priority", "P0" if item.get("type") in {"positive", "linkage"} else "P1")
        item.setdefault("automatable", item.get("type") != "linkage")
        signature = _case_signature(item)
        if signature in signatures:
            continue
        signatures.add(signature)
        cases.append(item)
        added += 1
    return added


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

        def point_kind(point: Mapping[str, Any]) -> str:
            raw_type = str(point.get("type") or "").casefold()
            if raw_type in {"linkage", "link", "联动"}:
                return "linkage"
            if raw_type in {"boundary", "performance", "concurrency", "边界"}:
                return "boundary"
            if raw_type in {"negative", "security", "exception", "异常", "安全"}:
                return "negative"
            return "positive"

        selected = (
            [item for item in candidates if point_kind(item[0]) == "positive"] if round_number == 1 else
            [item for item in candidates if point_kind(item[0]) == "negative"] if round_number == 2 else
            [item for item in candidates if point_kind(item[0]) == "boundary"] if round_number == 3 else
            [item for item in candidates if point_kind(item[0]) == "linkage"] if round_number == 4 else
            candidates
        )
        result = [
            _case(function, point_kind(point), round_number, test_point=point, linkage=linkage, variant="回归与兼容" if round_number == 5 else "")
            for point, function, linkage in selected
        ]
        if round_number == 4 and not result:
            for linkage in linkages:
                source = function_by_id.get(str(linkage.get("from")))
                if source:
                    result.append(_case(source, "linkage", 4, linkage=linkage))
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
        normalized = "negative" if kind in {"negative", "security", "exception", "异常", "安全"} else "boundary" if kind in {"boundary", "performance", "concurrency", "边界"} else "linkage" if kind in {"linkage", "link", "联动"} else "positive"
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
                offsets[key] = index + 1
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
) -> CaseGenerationResult:
    """Run five cumulative coverage passes with explicit model/fallback status."""
    payload = _analysis_payload(analysis)
    modules = payload.get("modules") if isinstance(payload.get("modules"), list) else []
    functions = payload.get("functions")
    test_points = payload.get("test_points") if isinstance(payload.get("test_points"), list) else []
    linkages = payload.get("linkages") if isinstance(payload.get("linkages"), list) else []
    if not isinstance(functions, list) or not functions:
        raise CaseGenerationError("需求分析结果没有可生成用例的功能点。")
    functions = [item for item in functions if isinstance(item, Mapping) and item.get("id")]
    if not functions:
        raise CaseGenerationError("功能点缺少有效标识。")
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

    cases: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    model_rounds: list[int] = []
    model_warnings: list[str] = []
    model_failures: list[dict[str, Any]] = []
    fallback_used = False
    use_incremental_model = bool(
        model_adapter
        and model_adapter.__class__.__module__ == "apps.case_generation.llm_adapter"
        and model_adapter.__class__.__name__ == "CaseGenerationModelAdapter"
    )

    for round_number in range(1, 6):
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
            added = _append_unique(cases, _annotate_model_cases(model_result.get("cases", []), test_points, linkages), round_number)
        else:
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

    unique: dict[tuple[str, str, str, tuple[str, ...], str, str], dict[str, Any]] = {}
    for item in cases:
        item["steps"] = [str(step).strip() for step in item.get("steps", []) if str(step).strip()]
        item["expected_result"] = str(item.get("expected_result") or "结果可验证").strip()
        unique.setdefault(_case_signature(item), item)
    cases = list(unique.values())
    cases.sort(key=lambda item: (str(item.get("source_function_id")), str(item.get("type"))))
    for index, item in enumerate(cases, start=1):
        item["id"] = f"case-{index:03d}"
    types = {kind: sum(item["type"] == kind for item in cases) for kind in ("positive", "negative", "boundary", "linkage")}
    model_verified = (model_rounds == [1, 2, 3, 4, 5] or (model_rounds == [1] and not use_incremental_model)) and not fallback_used
    method = "model_verified" if model_verified else ("deterministic_fallback" if fallback_used else ("model_partial" if model_rounds else "deterministic_baseline"))
    coverage: dict[str, Any] = {
        "module_count": len(modules),
        "function_count": len(functions),
        "test_point_count": len(test_points),
        "linkage_count": len(linkages),
        "case_count": len(cases),
        "types": types,
        "covered_function_ids": sorted({str(item["source_function_id"]) for item in cases}),
        "covered_test_point_ids": sorted({str(item.get("source_test_point_id")) for item in cases if item.get("source_test_point_id")}),
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
    }
    if route_metadata:
        coverage["model_route_resolution"] = dict(route_metadata)
    if model_warnings:
        coverage["model_warning"] = "；".join(model_warnings)
    return CaseGenerationResult(cases, coverage, trace)


def generate_document_cases(
    document: RequirementDocument,
    analysis: RequirementAnalysis | None = None,
    *,
    preferred_model_name: str | None = None,
) -> CaseGenerationRecord:
    """Persist one five-round generation run for a project requirement document."""
    source = analysis or document.analyses.order_by("-created_at").first()
    if source is None:
        raise CaseGenerationError("需求文档尚未完成需求分析。")
    if source.quality_status != RequirementAnalysis.QualityStatus.COMPLETE:
        raise CaseGenerationError("当前需求分析结果覆盖不完整或数量发生明显下降，请先复核并重新执行需求分析。")
    record = CaseGenerationRecord.objects.create(
        project=document.project,
        document=document,
        status=CaseGenerationRecord.Status.GENERATING,
    )
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
            allow_deterministic_baseline=not has_compatible_model,
            route_metadata=route.as_dict(),
        )
        record.rounds = 5
        record.total_cases = len(result.cases)
        record.auto_cases = sum(1 for item in result.cases if item["automatable"])
        record.manual_cases = record.total_cases - record.auto_cases
        record.cases = result.cases
        record.coverage_report = {**result.coverage_report, "round_trace": result.round_trace}
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


__all__ = ["CaseGenerationError", "CaseGenerationResult", "generate_cases", "generate_document_cases"]
