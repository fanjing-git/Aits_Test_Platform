"""Fingerprints, coverage checks, and comparisons for T155B."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


ANALYSIS_SCHEMA_VERSION = "requirement-analysis-v1"
COUNT_FIELDS = ("modules", "functions", "linkages", "test_points")
TEST_POINT_TYPES = {"positive", "negative", "boundary", "security", "linkage", "performance"}


def analysis_mapping_gaps(payload: Mapping[str, Any]) -> dict[str, list[str]]:
    """Find broken module/function/test-point relationships in an analysis."""
    modules = payload.get("modules") if isinstance(payload.get("modules"), list) else []
    functions = payload.get("functions") if isinstance(payload.get("functions"), list) else []
    linkages = payload.get("linkages") if isinstance(payload.get("linkages"), list) else []
    test_points = payload.get("test_points") if isinstance(payload.get("test_points"), list) else []
    module_ids = {str(item.get("id")) for item in modules if isinstance(item, Mapping) and item.get("id")}
    valid_function_ids = {
        str(item.get("id"))
        for item in functions
        if isinstance(item, Mapping) and item.get("id") and str(item.get("module_id", "")) in module_ids
    }
    valid_linkage_ids = {
        str(item.get("id"))
        for item in linkages
        if isinstance(item, Mapping)
        and item.get("id")
        and str(item.get("from") or item.get("source_function_id") or "") in valid_function_ids
        and str(item.get("to") or item.get("target_function_id") or "") in valid_function_ids
    }
    gaps = {
        "modules_without_name": sorted(
            str(item.get("id"))
            for item in modules
            if isinstance(item, Mapping)
            and item.get("id")
            and not str(item.get("name", "")).strip()
        ),
        "functions_without_module": sorted(
            str(item.get("id"))
            for item in functions
            if isinstance(item, Mapping)
            and item.get("id")
            and str(item.get("module_id", "")) not in module_ids
        ),
        "functions_without_name": sorted(
            str(item.get("id"))
            for item in functions
            if isinstance(item, Mapping)
            and item.get("id")
            and not str(item.get("name", "")).strip()
        ),
        "invalid_linkages": sorted(
            str(item.get("id"))
            for item in linkages
            if isinstance(item, Mapping)
            and item.get("id")
            and str(item.get("id")) not in valid_linkage_ids
        ),
        "test_points_without_parent": sorted(
            str(item.get("id"))
            for item in test_points
            if isinstance(item, Mapping)
            and item.get("id")
            and not (
                str(item.get("function_id") or item.get("source_function_id") or "") in valid_function_ids
                or str(item.get("scenario_id") or item.get("linkage_id") or "") in valid_linkage_ids
            )
        ),
        "test_points_without_description": sorted(
            str(item.get("id"))
            for item in test_points
            if isinstance(item, Mapping)
            and item.get("id")
            and not str(item.get("description", "")).strip()
        ),
        "test_points_without_type": sorted(
            str(item.get("id"))
            for item in test_points
            if isinstance(item, Mapping) and item.get("id") and not str(item.get("type", "")).strip()
        ),
        "test_points_with_unknown_type": sorted(
            str(item.get("id"))
            for item in test_points
            if isinstance(item, Mapping)
            and item.get("id")
            and str(item.get("type", "")).strip()
            and str(item.get("type", "")).strip().casefold() not in TEST_POINT_TYPES
        ),
    }
    return {key: value for key, value in gaps.items() if value}


def _digest(value: Any) -> str:
    """Return a stable SHA-256 digest for non-secret comparison metadata."""
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_source_fingerprint(
    *,
    content_text: str,
    source_type: str,
    version: str,
    evidence: Sequence[Mapping[str, Any]],
) -> str:
    """Fingerprint the parsed source without storing source text in diagnostics."""
    normalized_evidence = [
        {"id": str(item.get("id", "")), "text": str(item.get("text", "")), "type": str(item.get("type", ""))}
        for item in evidence
    ]
    return _digest({
        "content_text": str(content_text or "").replace("\r\n", "\n").strip(),
        "source_type": str(source_type),
        "version": str(version),
        "evidence": normalized_evidence,
    })


def build_analysis_fingerprint(source_fingerprint: str, coverage_report: Mapping[str, Any]) -> str:
    """Fingerprint the source plus safe model, prompt, and schema provenance."""
    route = coverage_report.get("model_route") if isinstance(coverage_report.get("model_route"), Mapping) else {}
    candidates = route.get("candidates", []) if isinstance(route, Mapping) else []
    safe_candidates = []
    for candidate in candidates if isinstance(candidates, list) else []:
        if isinstance(candidate, Mapping):
            safe_candidates.append({
                "id": candidate.get("id"),
                "name": candidate.get("name"),
                "provider": candidate.get("provider"),
                "model_name": candidate.get("model_name"),
                "source": candidate.get("source"),
            })
    return _digest({
        "source_fingerprint": source_fingerprint,
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "task_type": coverage_report.get("call_stage", "requirement_analysis"),
        "model_candidates": safe_candidates,
        "prompt": coverage_report.get("prompt_provenance", {}),
    })


def count_payload(payload: Mapping[str, Any]) -> dict[str, int]:
    """Count the four user-visible analysis collections."""
    return {key: len(payload.get(key, [])) if isinstance(payload.get(key), list) else 0 for key in COUNT_FIELDS}


def analysis_baseline(
    *,
    source_fingerprint: str,
    analysis_fingerprint: str,
    quality_status: str,
    counts: Mapping[str, int],
) -> dict[str, Any]:
    """Build a safe baseline summary that contains no requirement text."""
    return {
        "source_fingerprint": source_fingerprint,
        "analysis_fingerprint": analysis_fingerprint,
        "quality_status": quality_status,
        "counts": {key: int(counts.get(key, 0)) for key in COUNT_FIELDS},
    }


def compare_counts(current: Mapping[str, int], previous: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Compare counts with a prior baseline and flag material decreases."""
    previous_counts = previous.get("counts") if isinstance(previous, Mapping) else None
    if not isinstance(previous_counts, Mapping):
        return None
    delta = {key: int(current.get(key, 0)) - int(previous_counts.get(key, 0)) for key in COUNT_FIELDS}
    dropped = {
        key: {
            "previous": int(previous_counts.get(key, 0)),
            "current": int(current.get(key, 0)),
            "delta": delta[key],
            "drop_ratio": round((int(previous_counts.get(key, 0)) - int(current.get(key, 0))) / max(1, int(previous_counts.get(key, 0))), 4),
        }
        for key in COUNT_FIELDS
        if int(previous_counts.get(key, 0)) > 0 and delta[key] < 0
    }
    material_drop = any(item["drop_ratio"] >= 0.2 for item in dropped.values())
    return {
        "baseline_source": previous.get("baseline_source", "previous_analysis"),
        "previous_quality_status": previous.get("quality_status", "unknown"),
        "previous_analysis_fingerprint": previous.get("analysis_fingerprint", ""),
        "previous_counts": {key: int(previous_counts.get(key, 0)) for key in COUNT_FIELDS},
        "current_counts": dict(current),
        "delta": delta,
        "dropped": dropped,
        "material_drop": material_drop,
    }


def assess_quality(
    *,
    payload: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
    coverage_report: Mapping[str, Any],
    previous_baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assess evidence coverage and material count changes without judging semantics."""
    evidence_ids = {str(item.get("id")) for item in evidence if item.get("id")}
    covered_ids: set[str] = set()
    uncited_items = 0
    for key in COUNT_FIELDS:
        items = payload.get(key, []) if isinstance(payload.get(key), list) else []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            cited = item.get("evidence_ids")
            if not isinstance(cited, list) or not cited:
                uncited_items += 1
                continue
            covered_ids.update(str(value) for value in cited if str(value) in evidence_ids)

    structured = coverage_report.get("structured_generation") if isinstance(coverage_report.get("structured_generation"), Mapping) else {}
    structured_status = str(structured.get("status", "completed"))
    counts = count_payload(payload)
    comparison = compare_counts(counts, previous_baseline)
    mapping_gaps = analysis_mapping_gaps(payload)
    uncovered_ids = sorted(evidence_ids - covered_ids)
    has_inventory = bool(evidence_ids)
    coverage_ratio = round(len(covered_ids) / max(1, len(evidence_ids)), 4) if has_inventory else 0.0
    if structured_status != "completed":
        quality_status = "partial"
        reason = "存在未完成或失败的结构化分段。"
    elif mapping_gaps:
        quality_status = "needs_review"
        reason = "最终分析结果存在模块/功能点归属、名称、测试点描述或测试类型缺失，不能进入用例生成。"
    elif has_inventory and (uncovered_ids or uncited_items):
        quality_status = "needs_review"
        reason = "存在未覆盖证据或未提供证据引用的分析项。"
    elif not has_inventory and coverage_report.get("analysis_method") == "deterministic_evidence_baseline":
        quality_status = "complete"
        reason = "确定性证据基线已完成；该结果不代表模型已验证。"
    elif not has_inventory:
        quality_status = "needs_review"
        reason = "当前没有可用于完整性校验的解析证据清单。"
    elif comparison and comparison["material_drop"]:
        quality_status = "needs_review"
        reason = "本次结果相对上一版出现明显数量下降，需要人工复核。"
    else:
        quality_status = "complete"
        reason = "结构化分段和证据覆盖校验通过。"

    return {
        "quality_status": quality_status,
        "quality_reason": reason,
        "evidence_coverage": {
            "total_evidence": len(evidence_ids),
            "covered_evidence": len(covered_ids),
            "coverage_ratio": coverage_ratio,
            "uncovered_evidence_ids": uncovered_ids,
            "uncited_item_count": uncited_items,
        },
        "mapping_gaps": mapping_gaps,
        "counts": counts,
        "comparison": comparison,
        "needs_confirmation": quality_status != "complete" or bool(coverage_report.get("needs_confirmation")),
    }


__all__ = [
    "ANALYSIS_SCHEMA_VERSION",
    "COUNT_FIELDS",
    "TEST_POINT_TYPES",
    "analysis_mapping_gaps",
    "analysis_baseline",
    "assess_quality",
    "build_analysis_fingerprint",
    "build_source_fingerprint",
    "compare_counts",
    "count_payload",
]
