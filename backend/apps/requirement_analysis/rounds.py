"""Five-round semantic requirement review orchestration for T155C."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from core.task_state import CancelCheck, ProgressCallback, ensure_not_cancelled
from apps.requirement_analysis.llm_adapter import ModelAnalysisError, RequirementModelAdapter


ROUND_DEFINITIONS: tuple[dict[str, str], ...] = (
    {"name": "基础拆解", "focus": "模块、功能点、主流程、数据对象、初始测试点和原文证据。"},
    {"name": "异常风险", "focus": "异常、权限、输入校验、依赖失败、网络失败、安全和错误反馈。"},
    {"name": "边界状态", "focus": "边界值、空值、重复提交、并发、状态切换、恢复、重试和一致性。"},
    {"name": "关系联动", "focus": "模块依赖、数据流、接口契约、跨模块流程、状态联动和联合测试点。"},
    {"name": "最终复核", "focus": "证据覆盖、结构归属、测试类型、重复项、冲突项和高风险回归遗漏。"},
)
ROUND_COUNT = len(ROUND_DEFINITIONS)
MAX_CONTEXT_CHARS = 120000


def _text(value: Any) -> str:
    """Normalize user-visible text for stable comparison."""
    return " ".join(str(value or "").casefold().split())


def _json(value: Any, limit: int = MAX_CONTEXT_CHARS) -> str:
    """Serialize bounded audit context without exposing secrets."""
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return serialized[:limit]


def _stable_key(collection: str, item: Mapping[str, Any]) -> tuple[str, ...]:
    """Return a semantic identity that does not trust model-generated IDs."""
    if collection == "modules":
        return (collection, _text(item.get("name")))
    if collection == "functions":
        return (collection, _text(item.get("module_id")), _text(item.get("name")))
    if collection == "linkages":
        return (
            collection,
            _text(item.get("from") or item.get("source_function_id")),
            _text(item.get("to") or item.get("target_function_id")),
            _text(item.get("relationship") or item.get("description")),
        )
    return (
        collection,
        _text(item.get("function_id") or item.get("source_function_id") or item.get("scenario_id") or item.get("linkage_id")),
        _text(item.get("type")),
        _text(item.get("description") or item.get("scenario")),
    )


def _content_signature(item: Mapping[str, Any]) -> str:
    """Compare semantic content while ignoring provenance and generated IDs."""
    ignored = {"id", "evidence_ids", "source_segment_id", "source_round", "source_rounds"}
    return _json({key: value for key, value in item.items() if key not in ignored})


def _rewrite_refs(item: Mapping[str, Any], id_map: Mapping[str, str]) -> dict[str, Any]:
    """Rewrite model references to canonical IDs from earlier rounds."""
    result = dict(item)
    for key in ("module_id", "function_id", "source_function_id", "scenario_id", "linkage_id", "from", "to", "source_id", "target_id"):
        if key in result and not isinstance(result[key], (dict, list)):
            result[key] = id_map.get(str(result[key]), result[key])
    return result


_PROVENANCE_FIELDS = {
    "id", "evidence_ids", "source_segment_id", "source_round", "source_rounds", "source_segments",
}


def _round_values(values: Sequence[Any], fallback: int) -> list[int]:
    """Normalize round provenance from current and legacy payloads."""
    normalized: set[int] = set()
    for value in values:
        try:
            normalized.add(int(value))
        except (TypeError, ValueError):
            continue
    return sorted(normalized or {fallback})


def _merge_provenance(existing: dict[str, Any], incoming: Mapping[str, Any], round_number: int) -> None:
    """Merge only provenance and evidence; never replace an existing semantic value."""
    existing["evidence_ids"] = sorted({
        str(value)
        for value in (existing.get("evidence_ids") or []) + (incoming.get("evidence_ids") or [])
        if value
    })
    existing["source_rounds"] = _round_values(
        (existing.get("source_rounds") or [existing.get("source_round") or round_number]) + [round_number],
        round_number,
    )
    source_segments = [
        str(value)
        for value in (existing.get("source_segments") or []) + [
            existing.get("source_segment_id"), incoming.get("source_segment_id")
        ]
        if value
    ]
    if source_segments:
        existing["source_segments"] = sorted(set(source_segments))


def _conflict_record(
    *,
    collection: str,
    existing: Mapping[str, Any],
    incoming: Mapping[str, Any],
    stable_key: tuple[str, ...],
    reason: str,
    round_number: int,
    conflict_number: int,
) -> dict[str, Any]:
    """Create a reviewable, bounded audit record for a non-destructive merge conflict."""
    fields: list[dict[str, Any]] = []
    for field in sorted(set(existing) | set(incoming)):
        if field in _PROVENANCE_FIELDS:
            continue
        old_value = existing.get(field)
        new_value = incoming.get(field)
        if _json(old_value) == _json(new_value):
            continue
        fields.append({
            "field": field,
            "existing_value": old_value,
            "incoming_value": new_value,
            "existing_source_rounds": _round_values(existing.get("source_rounds") or [existing.get("source_round")], round_number),
            "incoming_source_round": round_number,
            "existing_source_segment_id": existing.get("source_segment_id"),
            "incoming_source_segment_id": incoming.get("source_segment_id"),
        })
    return {
        "id": f"conflict-r{round_number}-{collection}-{conflict_number}",
        "collection": collection,
        "entity_id": str(existing.get("id") or ""),
        "incoming_id": str(incoming.get("id") or "") or None,
        "stable_key": list(stable_key),
        "reason": reason,
        "round": round_number,
        "status": "pending",
        "resolution": "preserve_existing",
        "fields": fields,
        "audit": {
            "existing_source_rounds": _round_values(existing.get("source_rounds") or [existing.get("source_round")], round_number),
            "incoming_source_round": round_number,
            "existing_source_segment_id": existing.get("source_segment_id"),
            "incoming_source_segment_id": incoming.get("source_segment_id"),
        },
    }


def _merge_round_payload(
    accumulated: dict[str, list[dict[str, Any]]],
    payload: Mapping[str, Any],
    *,
    round_number: int,
) -> dict[str, Any]:
    """Merge one round, preserving provenance and explicit conflicts."""
    counts = {"added": 0, "updated": 0, "duplicate": 0, "conflict": 0}
    id_map: dict[str, str] = {}
    conflicts: list[dict[str, Any]] = []
    for collection in ("modules", "functions", "linkages", "test_points"):
        for raw in payload.get(collection, []) if isinstance(payload.get(collection), list) else []:
            if not isinstance(raw, Mapping):
                continue
            item = _rewrite_refs(raw, id_map)
            raw_id = str(item.get("id") or "").strip()
            key = _stable_key(collection, item)
            existing = next((candidate for candidate in accumulated[collection] if _stable_key(collection, candidate) == key), None)
            same_id = next((candidate for candidate in accumulated[collection] if raw_id and str(candidate.get("id")) == raw_id), None)
            if existing is None and same_id is not None:
                conflicts.append(_conflict_record(
                    collection=collection,
                    existing=same_id,
                    incoming=item,
                    stable_key=key,
                    reason="same_id_different_semantics",
                    round_number=round_number,
                    conflict_number=len(conflicts) + 1,
                ))
                counts["conflict"] += 1
                id_map[raw_id] = str(same_id.get("id"))
                _merge_provenance(same_id, item, round_number)
                continue
            if existing is not None:
                id_map[raw_id] = str(existing.get("id")) if raw_id else str(existing.get("id"))
                if _content_signature(existing) == _content_signature(item):
                    _merge_provenance(existing, item, round_number)
                    counts["duplicate"] += 1
                else:
                    conflicts.append(_conflict_record(
                        collection=collection,
                        existing=existing,
                        incoming=item,
                        stable_key=key,
                        reason="same_business_key_different_fields",
                        round_number=round_number,
                        conflict_number=len(conflicts) + 1,
                    ))
                    _merge_provenance(existing, item, round_number)
                    counts["conflict"] += 1
                continue
            if not raw_id:
                item["id"] = f"round-{round_number}-{collection}-{len(accumulated[collection]) + 1}"
            item["source_round"] = round_number
            item["source_rounds"] = [round_number]
            accumulated[collection].append(item)
            if raw_id:
                id_map[raw_id] = str(item["id"])
            counts["added"] += 1
    return {"counts": counts, "conflicts": conflicts}


def _segment_summary(coverage: Mapping[str, Any]) -> tuple[int, int, int, list[dict[str, Any]]]:
    """Read inner segment counts from an adapter coverage report."""
    structured = coverage.get("structured_generation") if isinstance(coverage.get("structured_generation"), Mapping) else {}
    trace = [dict(item) for item in structured.get("segments", []) if isinstance(item, Mapping)]
    segment_count = int(structured.get("segment_count") or len(trace) or 1)
    completed = int(structured.get("completed_segments") or sum(item.get("status") == "completed" for item in trace))
    calls = len(trace) or segment_count
    return segment_count, completed, calls, trace


def _round_prompt(round_number: int, accumulated: Mapping[str, Sequence[Mapping[str, Any]]], evidence: Sequence[Mapping[str, Any]]) -> str:
    """Build a bounded semantic-round instruction with full cumulative context."""
    definition = ROUND_DEFINITIONS[round_number - 1]
    prior = {key: list(value) for key, value in accumulated.items()}
    previous_context = "无，这是第一轮基线。" if round_number == 1 else _json({
        "accumulated_result": prior,
        "covered_evidence_ids": sorted({
            str(value)
            for group in prior.values()
            for item in group
            for value in (item.get("evidence_ids") or [])
        }),
        "all_evidence_ids": [str(item.get("id")) for item in evidence],
    })
    return (
        "只输出符合现有需求分析 Schema 的 JSON，不要 Markdown。顶层必须始终包含 modules、functions、linkages、test_points、coverage_report 五个字段；"
        "前四个字段必须始终是对象数组，即使本轮没有新增内容也必须输出空数组，不能省略字段或改成字符串。"
        f"当前是第 {round_number}/5 轮：{definition['name']}。本轮重点：{definition['focus']}"
        "必须重新阅读完整正文和全部证据；只输出本轮新增、修正、重复或冲突涉及的结构化对象，"
        "不得虚构无证据事实。保留有效的模块→功能点→测试点关系，测试点必须填写 type 和 evidence_ids。"
        "跨轮重复对象应保持稳定语义和 ID；若发现冲突，保留当前有效结果并在 coverage_report.conflicts 中说明。"
        f"前轮累计上下文如下：{previous_context}"
    )


def run_five_round_analysis(
    *,
    text: str,
    evidence: Sequence[Mapping[str, Any]],
    project_name: str | None = None,
    preferred_model_name: str | None = None,
    adapter: RequirementModelAdapter | None = None,
    resume_round: int = 1,
    prior_payload: Mapping[str, Any] | None = None,
    prior_rounds: Sequence[Mapping[str, Any]] = (),
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
    """Run five semantic rounds over complete requirement context.

    The adapter owns inner bounded segmentation. This service owns round context,
    cross-round merging, provenance and recoverable failure state.
    """
    if not str(text or "").strip():
        raise ModelAnalysisError("需求正文不能为空。", code="empty_input")
    if not 1 <= int(resume_round) <= ROUND_COUNT:
        raise ModelAnalysisError("恢复轮次必须在 1 到 5 之间。", code="invalid_round")
    current = {key: [dict(item) for item in (prior_payload or {}).get(key, []) if isinstance(item, Mapping)] for key in ("modules", "functions", "linkages", "test_points")}
    round_records = [dict(item) for item in prior_rounds if isinstance(item, Mapping) and int(item.get("round", 0) or 0) < int(resume_round)]
    runner = adapter or RequirementModelAdapter()
    total_calls = sum(int(item.get("calls", 0) or 0) for item in round_records)
    all_evidence_ids = {str(item.get("id")) for item in evidence if item.get("id")}

    for round_number in range(int(resume_round), ROUND_COUNT + 1):
        ensure_not_cancelled(cancel_check)
        definition = ROUND_DEFINITIONS[round_number - 1]
        record: dict[str, Any] = {"round": round_number, "name": definition["name"], "focus": definition["focus"], "status": "running", "added": 0, "updated": 0, "duplicate": 0, "conflict": 0, "uncovered_evidence": sorted(all_evidence_ids)}
        if progress_callback:
            progress_callback({
                "status": "running",
                "current_step": f"需求分析·第{round_number}轮",
                "current_round": round_number,
                "total_rounds": ROUND_COUNT,
                "completed_rounds": round_number - 1,
                "round": dict(record),
            })
        try:
            payload = runner.analyze(
                text=text,
                evidence=evidence,
                project_name=project_name,
                preferred_model_name=preferred_model_name,
                prompt_override=_round_prompt(round_number, current, evidence),
            )
            merge = _merge_round_payload(current, payload, round_number=round_number)
            coverage = payload.get("coverage_report") if isinstance(payload.get("coverage_report"), Mapping) else {}
            segment_count, completed_segments, calls, trace = _segment_summary(coverage)
            cited_ids = {str(value) for collection in current.values() for item in collection for value in (item.get("evidence_ids") or []) if str(value) in all_evidence_ids}
            record.update({
                "status": "completed",
                "added": merge["counts"]["added"],
                "updated": merge["counts"]["updated"],
                "duplicate": merge["counts"]["duplicate"],
                "conflict": merge["counts"]["conflict"],
                "conflicts": merge["conflicts"],
                "segment_count": segment_count,
                "completed_segments": completed_segments,
                "calls": calls,
                "segments": trace,
                "model_route": coverage.get("model_route", {}),
                "coverage_rate": round(len(cited_ids) / max(1, len(all_evidence_ids)), 4) if all_evidence_ids else 0.0,
                "uncovered_evidence": sorted(all_evidence_ids - cited_ids),
            })
            round_records.append(record)
            total_calls += calls
            if progress_callback:
                progress_callback({
                    "status": "running",
                    "current_step": f"需求分析·第{round_number}轮已完成",
                    "current_round": round_number,
                    "total_rounds": ROUND_COUNT,
                    "completed_rounds": round_number,
                    "round": dict(record),
                })
        except ModelAnalysisError as exc:
            partial = exc.partial_payload if isinstance(exc.partial_payload, Mapping) else {}
            if partial:
                merge = _merge_round_payload(current, partial, round_number=round_number)
                record.update({"added": merge["counts"]["added"], "updated": merge["counts"]["updated"], "duplicate": merge["counts"]["duplicate"], "conflict": merge["counts"]["conflict"], "conflicts": merge["conflicts"]})
            segment_count, completed_segments, calls, trace = _segment_summary(partial.get("coverage_report", {}) if isinstance(partial, Mapping) else {})
            record.update({"status": "failed", "segment_count": segment_count, "completed_segments": completed_segments, "calls": calls, "segments": trace, "failure_reason": str(exc), "error_code": exc.code})
            round_records.append(record)
            total_calls += calls
            if progress_callback:
                progress_callback({
                    "status": "failed",
                    "current_step": f"需求分析·第{round_number}轮失败",
                    "current_round": round_number,
                    "total_rounds": ROUND_COUNT,
                    "completed_rounds": sum(item.get("status") == "completed" for item in round_records),
                    "round": dict(record),
                    "error_code": exc.code,
                })
            all_conflicts = [item for round_item in round_records for item in round_item.get("conflicts", [])]
            conflict_ids = [str(item.get("id")) for item in all_conflicts if item.get("id")]
            failure_payload = {
                **current,
                "coverage_report": {
                    "round_count": ROUND_COUNT,
                    "completed_rounds": sum(item.get("status") == "completed" for item in round_records),
                    "round_execution_status": "partial" if current["modules"] or current["test_points"] else "failed",
                    "rounds": round_records,
                    "round_progress": {"current_round": round_number, "total_rounds": ROUND_COUNT, "status": "partial" if current["modules"] or current["test_points"] else "failed"},
                    "total_calls": total_calls,
                    "error_code": exc.code,
                    "failure_reason": str(exc),
                    "conflicts": all_conflicts,
                    "conflict_review": {
                        "required": bool(all_conflicts),
                        "status": "pending" if all_conflicts else "not_required",
                        "pending_conflict_ids": conflict_ids,
                        "resolved_conflict_ids": [],
                    },
                    "conflict_audit_trail": all_conflicts,
                },
            }
            raise ModelAnalysisError(str(exc), code=exc.code, structured_trace=exc.structured_trace, partial_payload=failure_payload) from exc

    cumulative_counts = {key: len(value) for key, value in current.items()}
    all_conflicts = [item for round_item in round_records for item in round_item.get("conflicts", [])]
    conflict_ids = [str(item.get("id")) for item in all_conflicts if item.get("id")]
    return {
        **current,
        "coverage_report": {
            "round_count": ROUND_COUNT,
            "completed_rounds": ROUND_COUNT,
            "round_execution_status": "completed",
            "rounds": round_records,
            "round_progress": {"current_round": ROUND_COUNT, "total_rounds": ROUND_COUNT, "status": "completed"},
            "total_calls": total_calls,
            "accumulated_counts": cumulative_counts,
            "conflicts": all_conflicts,
            "conflict_review": {
                "required": bool(all_conflicts),
                "status": "pending" if all_conflicts else "not_required",
                "pending_conflict_ids": conflict_ids,
                "resolved_conflict_ids": [],
            },
            "conflict_audit_trail": all_conflicts,
        },
    }


__all__ = ["ROUND_COUNT", "ROUND_DEFINITIONS", "run_five_round_analysis"]
