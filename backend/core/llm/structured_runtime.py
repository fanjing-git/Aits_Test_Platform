"""Bounded segmented execution and deterministic merging for JSON model calls."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class StructuredSegment:
    """One bounded, traceable structured-model input segment."""

    segment_id: str
    text: str
    evidence: tuple[Mapping[str, Any], ...] = ()
    depth: int = 0

    @property
    def input_chars(self) -> int:
        """Return a conservative character-size estimate for diagnostics."""
        return len(self.text) + len(json.dumps(list(self.evidence), ensure_ascii=False, default=str))


class StructuredBatchError(RuntimeError):
    """Raised when a segmented run stops with recoverable or terminal failure."""

    def __init__(
        self,
        message: str,
        *,
        trace: Sequence[Mapping[str, Any]],
        partial_payloads: Sequence[tuple[StructuredSegment, Mapping[str, Any]]] = (),
    ) -> None:
        super().__init__(message)
        self.trace = tuple(dict(item) for item in trace)
        self.partial_payloads = tuple(partial_payloads)


def _split_text(text: str, limit: int) -> list[str]:
    """Split text at paragraph or whitespace boundaries without dropping content."""
    normalized = str(text or "")
    if len(normalized) <= limit:
        return [normalized]
    paragraphs = [item for item in normalized.replace("\r\n", "\n").split("\n\n") if item.strip()]
    parts: list[str] = []
    current = ""
    for paragraph in paragraphs or [normalized]:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if current and len(candidate) > limit:
            parts.append(current)
            current = paragraph
            continue
        if len(paragraph) <= limit:
            current = candidate
            continue
        for start in range(0, len(paragraph), limit):
            piece = paragraph[start : start + limit]
            if current:
                parts.append(current)
                current = ""
            parts.append(piece)
    if current:
        parts.append(current)
    return parts or [normalized[:limit]]


def _chunk_evidence(evidence: Sequence[Mapping[str, Any]], limit: int, max_items: int) -> list[tuple[Mapping[str, Any], ...]]:
    """Group evidence by count and serialized size while preserving order."""
    if not evidence:
        return [()]
    groups: list[tuple[Mapping[str, Any], ...]] = []
    current: list[Mapping[str, Any]] = []
    current_chars = 2
    for item in evidence:
        serialized_chars = len(json.dumps(item, ensure_ascii=False, default=str)) + 1
        if current and (len(current) >= max_items or current_chars + serialized_chars > limit):
            groups.append(tuple(current))
            current = []
            current_chars = 2
        current.append(item)
        current_chars += serialized_chars
    if current:
        groups.append(tuple(current))
    return groups


def plan_structured_segments(
    text: str,
    evidence: Sequence[Mapping[str, Any]],
    *,
    max_input_chars: int = 24000,
    max_evidence_items: int = 32,
) -> tuple[StructuredSegment, ...]:
    """Create bounded segments at stable paragraph/evidence boundaries."""
    max_input_chars = max(2000, int(max_input_chars))
    max_evidence_items = max(1, int(max_evidence_items))
    text_parts = _split_text(str(text or ""), max_input_chars)
    evidence_groups = _chunk_evidence(evidence, max_input_chars, max_evidence_items)
    count = max(len(text_parts), len(evidence_groups))
    segments: list[StructuredSegment] = []
    for index in range(count):
        text_part = text_parts[min(index, len(text_parts) - 1)]
        evidence_part = evidence_groups[min(index, len(evidence_groups) - 1)]
        segments.append(StructuredSegment(f"segment-{index + 1:04d}", text_part, evidence_part))
    return tuple(segments)


def split_segment(segment: StructuredSegment) -> tuple[StructuredSegment, ...]:
    """Split one segment after an output truncation, if a safe split exists."""
    if len(segment.evidence) > 1:
        midpoint = max(1, len(segment.evidence) // 2)
        groups = (segment.evidence[:midpoint], segment.evidence[midpoint:])
        return tuple(
            StructuredSegment(f"{segment.segment_id}-{index + 1}", segment.text, group, segment.depth + 1)
            for index, group in enumerate(groups)
            if group
        )
    if len(segment.text) > 2000:
        parts = _split_text(segment.text, max(1000, len(segment.text) // 2))
        if len(parts) > 1:
            return tuple(
                StructuredSegment(f"{segment.segment_id}-{index + 1}", part, segment.evidence, segment.depth + 1)
                for index, part in enumerate(parts)
            )
    return ()


_REFERENCE_FIELDS = {
    "module_id", "source_function_id", "function_id", "linkage_id", "case_id",
    "from", "to", "source_id", "target_id", "parent_id",
}


def _item_signature(item: Mapping[str, Any]) -> str:
    """Build a stable semantic signature for items without trusting model IDs."""
    normalized = {key: value for key, value in item.items() if key not in {"id", "source_segment_id"}}
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str)


def _rewrite_references(value: Any, id_map: Mapping[str, str]) -> Any:
    """Rewrite known references from one segment after ID collision repair."""
    if isinstance(value, list):
        return [_rewrite_references(item, id_map) for item in value]
    if isinstance(value, dict):
        return {
            key: id_map.get(str(item), item) if key in _REFERENCE_FIELDS and not isinstance(item, (dict, list)) else _rewrite_references(item, id_map)
            for key, item in value.items()
        }
    return value


def merge_structured_payloads(
    payloads: Sequence[tuple[StructuredSegment, Mapping[str, Any]]],
) -> dict[str, Any]:
    """Merge segmented JSON objects, repair ID collisions and retain provenance."""
    if not payloads:
        return {}
    merged: dict[str, Any] = {}
    seen_ids: dict[str, tuple[str, str]] = {}
    seen_signatures: dict[str, str] = {}
    segment_maps: dict[str, dict[str, str]] = {}
    list_keys: list[str] = []

    for segment, payload in payloads:
        local_map: dict[str, str] = {}
        segment_maps[segment.segment_id] = local_map
        for key, raw_items in payload.items():
            if key == "coverage_report" or not isinstance(raw_items, list):
                continue
            if key not in list_keys:
                list_keys.append(key)
            target = merged.setdefault(key, [])
            for raw_item in raw_items:
                if not isinstance(raw_item, Mapping):
                    continue
                item = dict(raw_item)
                raw_id = str(item.get("id", "")).strip()
                signature = _item_signature(item)
                signature_key = f"{key}:{signature}"
                if signature_key in seen_signatures:
                    if raw_id:
                        local_map[raw_id] = seen_signatures[signature_key]
                    continue
                new_id = raw_id
                if raw_id and raw_id in seen_ids:
                    new_id = f"{raw_id}__{segment.segment_id}"
                    suffix = 2
                    while new_id in seen_ids:
                        new_id = f"{raw_id}__{segment.segment_id}_{suffix}"
                        suffix += 1
                if new_id:
                    item["id"] = new_id
                    seen_ids[new_id] = (key, segment.segment_id)
                    if raw_id:
                        local_map[raw_id] = new_id
                item.setdefault("source_segment_id", segment.segment_id)
                target.append(item)
                seen_signatures[signature_key] = new_id or f"{key}-{len(target)}"

    for segment, payload in payloads:
        id_map = segment_maps.get(segment.segment_id, {})
        for key in list_keys:
            items = payload.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                signature = _item_signature(item)
                target_id = seen_signatures.get(f"{key}:{signature}")
                if not target_id:
                    continue
                target = next((candidate for candidate in merged[key] if candidate.get("id") == target_id), None)
                if target is not None:
                    target.update(_rewrite_references(dict(item), id_map))
                    target["id"] = target_id
                    target.setdefault("source_segment_id", segment.segment_id)

    coverage: dict[str, Any] = {}
    for _segment, payload in payloads:
        value = payload.get("coverage_report")
        if isinstance(value, Mapping):
            coverage.update(dict(value))
        for key, value in payload.items():
            if key == "coverage_report" or isinstance(value, list) or key in merged:
                continue
            merged[key] = value
    merged["coverage_report"] = coverage
    return merged


@dataclass(frozen=True)
class StructuredBatchResult:
    """Successful merged payload and its segment-level execution trace."""

    payload: dict[str, Any]
    trace: tuple[dict[str, Any], ...]


def execute_structured_segments(
    segments: Sequence[StructuredSegment],
    call: Callable[[StructuredSegment], Mapping[str, Any]],
    *,
    max_segments: int = 128,
) -> StructuredBatchResult:
    """Execute bounded segments and split only when output truncation is reported."""
    queue = list(segments)
    completed: list[tuple[StructuredSegment, Mapping[str, Any]]] = []
    trace: list[dict[str, Any]] = []
    processed = 0
    while queue:
        if processed >= max_segments:
            raise StructuredBatchError("结构化分段数量超过安全上限。", trace=trace, partial_payloads=completed)
        segment = queue.pop(0)
        processed += 1
        try:
            payload = call(segment)
            completed.append((segment, payload))
            trace.append({
                "segment_id": segment.segment_id,
                "status": "completed",
                "input_chars": segment.input_chars,
                "evidence_count": len(segment.evidence),
                "evidence_ids": [str(item.get("id")) for item in segment.evidence if item.get("id")],
                "attempts": 1,
            })
        except Exception as exc:
            code = getattr(exc, "code", "")
            children = split_segment(segment) if code == "output_truncated" else ()
            if children:
                trace.append({
                    "segment_id": segment.segment_id,
                    "status": "split_after_output_truncated",
                    "input_chars": segment.input_chars,
                    "evidence_count": len(segment.evidence),
                    "evidence_ids": [str(item.get("id")) for item in segment.evidence if item.get("id")],
                    "attempts": 1,
                    "error_code": code,
                    "children": [child.segment_id for child in children],
                })
                queue[0:0] = list(children)
                continue
            trace.append({
                "segment_id": segment.segment_id,
                "status": "failed",
                "input_chars": segment.input_chars,
                "evidence_count": len(segment.evidence),
                "evidence_ids": [str(item.get("id")) for item in segment.evidence if item.get("id")],
                "attempts": 1,
                "error_code": code or "structured_generation_error",
                "error": str(exc),
            })
            raise StructuredBatchError("结构化分段调用失败。", trace=trace, partial_payloads=completed) from exc
    return StructuredBatchResult(merge_structured_payloads(completed), tuple(trace))


__all__ = [
    "StructuredBatchError",
    "StructuredBatchResult",
    "StructuredSegment",
    "execute_structured_segments",
    "merge_structured_payloads",
    "plan_structured_segments",
    "split_segment",
]
