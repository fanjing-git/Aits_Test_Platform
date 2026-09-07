"""Deterministic five-round test case generation from requirement analysis."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from apps.configs.models import ModelConfig
from apps.case_generation.models import CaseGenerationRecord
from apps.case_generation.llm_adapter import CaseGenerationModelAdapter
from apps.requirement_analysis.llm_adapter import ModelAnalysisError
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


def _case(function: Mapping[str, Any], kind: str, round_added: int, *, linkage: Mapping[str, Any] | None = None, variant: str = "") -> dict[str, Any]:
    """Build one safe, reviewable test case without executing a target system."""
    name = str(function.get("name") or function.get("description") or "未命名功能").strip()
    labels = {"positive": "正常流程", "negative": "异常与权限", "boundary": "边界条件", "linkage": "跨模块联动"}
    return {
        "id": "",
        "title": f"{name} - {labels[kind]}{f' - {variant}' if variant else ''}",
        "type": kind,
        "priority": "P0" if kind in {"positive", "linkage"} else "P1",
        "source_function_id": function.get("id"),
        "steps": [f"准备{function.get('module_id', '目标模块')}所需数据", f"执行{name}"],
        "expected_result": f"{name}符合需求并返回可验证结果",
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


def _deterministic_round(functions: list[Mapping[str, Any]], linkages: list[Mapping[str, Any]], round_number: int) -> list[dict[str, Any]]:
    """Create a bounded fallback increment for one coverage dimension."""
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


def generate_cases(
    analysis: RequirementAnalysis | Mapping[str, Any],
    *,
    model_adapter: CaseGenerationModelAdapter | None = None,
    evidence: list[dict[str, Any]] | None = None,
    project_name: str | None = None,
    document_text: str = "",
    preferred_model_name: str | None = None,
    allow_deterministic_baseline: bool = True,
) -> CaseGenerationResult:
    """Run five cumulative coverage passes, using the model once per pass when available."""
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
    cases: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    model_rounds: list[int] = []
    model_warnings: list[str] = []
    use_incremental_model = bool(
        model_adapter
        and model_adapter.__class__.__module__ == "apps.case_generation.llm_adapter"
        and model_adapter.__class__.__name__ == "CaseGenerationModelAdapter"
    )
    for round_number in range(1, 6):
        before = len(cases)
        stage = "model_incremental"
        note = "模型基于需求分析、测试点和已有用例补充本轮覆盖"
        round_analysis: dict[str, Any] = {}
        if use_incremental_model and model_adapter:
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
                added = _append_unique(cases, model_result["cases"], round_number)
                round_analysis = model_result.get("round_analysis", {}) if isinstance(model_result.get("round_analysis"), dict) else {}
                model_rounds.append(round_number)
            except ModelAnalysisError as exc:
                if not allow_deterministic_baseline:
                    raise CaseGenerationError(f"\u7b2c{round_number}\u8f6e\u6a21\u578b\u8c03\u7528\u5931\u8d25\uff0c\u672a\u751f\u6210\u786e\u5b9a\u6027\u66ff\u4ee3\u7ed3\u679c\uff1a{exc}") from exc
                model_warnings.append(f"第{round_number}轮：{exc}")
                added = _append_unique(cases, _deterministic_round(functions, linkages, round_number), round_number)
                stage = "deterministic_fallback"
                note = "模型本轮不可用，使用确定性覆盖补全"
        else:
            # Backward-compatible single-pass fakes remain supported in tests and integrations.
            if round_number == 1 and model_adapter:
                try:
                    model_result = model_adapter.generate(functions=functions, linkages=linkages, evidence=evidence or [], project_name=project_name)
                    added = _append_unique(cases, model_result["cases"], 1)
                    round_analysis = model_result.get("round_analysis", {}) if isinstance(model_result.get("round_analysis"), dict) else {}
                    model_rounds.append(1)
                except ModelAnalysisError as exc:
                    if not allow_deterministic_baseline:
                        raise CaseGenerationError(f"\u7b2c1\u8f6e\u6a21\u578b\u8c03\u7528\u5931\u8d25\uff0c\u672a\u751f\u6210\u786e\u5b9a\u6027\u66ff\u4ee3\u7ed3\u679c\uff1a{exc}") from exc
                    model_warnings.append(f"第1轮：{exc}")
                    added = _append_unique(cases, _deterministic_round(functions, linkages, 1), 1)
                    stage = "deterministic_fallback"
                    note = "模型不可用，使用确定性覆盖补全"
            else:
                added = _append_unique(cases, _deterministic_round(functions, linkages, round_number), round_number)
                stage = "deterministic_baseline"
                note = "确定性覆盖基线"
        trace.append({"round": round_number, "stage": stage, "added": added, "total": len(cases), "note": note, "analysis": round_analysis})

    # Final normalization removes exact duplicates while retaining distinct scenarios.
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
    coverage = {
        "module_count": len(modules),
        "function_count": len(functions),
        "test_point_count": len(test_points),
        "linkage_count": len(linkages),
        "case_count": len(cases),
        "types": types,
        "covered_function_ids": sorted({str(item["source_function_id"]) for item in cases}),
        "coverage_rate": round(len({str(item["source_function_id"]) for item in cases}) / len(functions), 4),
        "analysis_method": (
            "model_verified"
            if len(model_rounds) == 5 or (model_rounds == [1] and not use_incremental_model)
            else ("model_partial" if model_rounds else "deterministic_baseline")
        ),
        "model_rounds": model_rounds,
        "round_trace": trace,
    }
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
    record = CaseGenerationRecord.objects.create(project=document.project, document=document, status=CaseGenerationRecord.Status.GENERATING)
    try:
        model_adapter = None
        has_compatible_model = ModelConfig.objects.filter(
            is_active=True,
            model_type__in=(ModelConfig.ModelType.CHAT, ModelConfig.ModelType.MULTIMODAL, ModelConfig.ModelType.VISION),
        ).exists()
        if has_compatible_model:
            model_adapter = CaseGenerationModelAdapter()
        result = generate_cases(
            source,
            model_adapter=model_adapter,
            evidence=document.parse_evidence,
            project_name=document.project.name,
            document_text=document.content_text,
            preferred_model_name=preferred_model_name,
            allow_deterministic_baseline=not has_compatible_model,
        )
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
