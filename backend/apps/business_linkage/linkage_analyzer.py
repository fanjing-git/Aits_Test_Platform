"""LLM-backed business-linkage recognition with bounded, safe output validation."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from apps.configs.models import ModelConfig, ModelRoutingPolicy, PromptConfig
from apps.requirement_analysis.llm_adapter import OpenAICompatibleRuntime
from core.llm.manager import ModelFallbackExhausted, ModelManager, ModelNotFound
from core.llm.structured_runtime import (
    StructuredBatchError,
    StructuredSegment,
    execute_structured_segments,
    plan_structured_segments,
)
from core.prompts.manager import PromptManager


MAX_INTERFACE_DOCUMENTS = 256
MAX_INTERFACE_DOCUMENT_CHARS = 12000
MAX_INPUT_CHARS = 100000
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}$")
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:password|passwd|secret|api[_-]?key|authorization|token|cookie|set-cookie)",
    re.IGNORECASE,
)


class LinkageRuntime(Protocol):
    """Runtime protocol used by the recognizer and its non-network tests."""

    def generate_structured(
        self,
        *,
        prompt: str,
        text: str,
        evidence: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]: ...


class BusinessLinkageAnalysisError(RuntimeError):
    """Raised when linkage input or model output cannot be safely accepted."""

    def __init__(
        self,
        message: str,
        code: str = "invalid_response",
        *,
        trace: Sequence[Mapping[str, Any]] = (),
        partial_payload: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.trace = tuple(dict(item) for item in trace)
        self.partial_payload = dict(partial_payload or {})


LINKAGE_INSTRUCTION = """
只输出一个 JSON 对象，不要 Markdown、解释文字或虚构接口。分析输入的 API 接口定义，识别有明确业务先后关系的跨接口业务链路。
顶层必须包含 linkages 数组和 coverage_report 对象。每条 linkage 必须包含：id、name、description、evidence_ids、steps、dependencies。
每个 step 必须包含：id、interface_id、order、purpose、evidence_ids；interface_id 必须引用输入接口 id。
每个 dependency 必须包含：id、from_step_id、to_step_id、data_mappings、evidence_ids；from_step_id 和 to_step_id 必须引用同一链路中的步骤，并说明 token、ID、状态等数据如何传递。
只输出有接口定义证据支持的关系；没有足够证据的内容不要生成。一个业务链路至少包含两个不同接口和一条依赖关系。
所有 id 必须是唯一、稳定的字符串；所有 evidence_ids 必须来自当前输入证据。linkages 可以为空数组，但不得用空对象代替数组。
""".strip()


def _safe_identifier(value: Any, field_name: str) -> str:
    """Normalize one bounded identifier and reject ambiguous model references."""
    normalized = str(value or "").strip()
    if not normalized or not _IDENTIFIER_PATTERN.fullmatch(normalized):
        raise BusinessLinkageAnalysisError(
            f"{field_name} 必须是 1-200 个字母、数字或安全分隔符组成的字符串。",
            code="invalid_input" if field_name == "interface_id" else "invalid_response",
        )
    return normalized


def _redact_sensitive(value: Any, depth: int = 0) -> Any:
    """Redact credential-like fields before an interface document reaches a model."""
    if depth > 8:
        return "<depth-limited>"
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted>" if _SENSITIVE_KEY_PATTERN.search(str(key)) else _redact_sensitive(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive(item, depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return value[:MAX_INTERFACE_DOCUMENT_CHARS]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:MAX_INTERFACE_DOCUMENT_CHARS]


def _normalize_interface_documents(
    api_documents: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Validate and minimize interface definitions while retaining evidence IDs."""
    if isinstance(api_documents, (str, bytes)) or not isinstance(api_documents, Sequence):
        raise BusinessLinkageAnalysisError("接口文档必须是非空数组。", code="invalid_input")
    if not api_documents:
        raise BusinessLinkageAnalysisError("接口文档不能为空。", code="empty_input")
    if len(api_documents) > MAX_INTERFACE_DOCUMENTS:
        raise BusinessLinkageAnalysisError("接口文档数量超过安全上限。", code="input_too_large")

    normalized: list[dict[str, Any]] = []
    evidence: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for raw_document in api_documents:
        if not isinstance(raw_document, Mapping):
            raise BusinessLinkageAnalysisError("每个接口文档必须是对象。", code="invalid_input")
        raw_id = raw_document.get("id") or raw_document.get("operation_id")
        interface_id = _safe_identifier(raw_id, "interface_id")
        if interface_id in seen_ids:
            raise BusinessLinkageAnalysisError("接口 id 不能重复。", code="invalid_input")
        seen_ids.add(interface_id)
        method = str(raw_document.get("method") or "").strip().upper()
        path = str(raw_document.get("path") or raw_document.get("url") or "").strip()
        if not method or len(method) > 20 or not path or len(path) > 1000:
            raise BusinessLinkageAnalysisError("接口文档必须包含有效的 method 和 path。", code="invalid_input")

        selected: dict[str, Any] = {
            "id": interface_id,
            "method": method,
            "path": path,
        }
        for key in (
            "operation_id",
            "summary",
            "description",
            "tags",
            "parameters",
            "request",
            "request_schema",
            "response",
            "response_schema",
            "security",
        ):
            if key in raw_document:
                selected[key] = _redact_sensitive(raw_document[key])
        serialized = json.dumps(selected, ensure_ascii=False, sort_keys=True, default=str)
        if len(serialized) > MAX_INTERFACE_DOCUMENT_CHARS:
            serialized = serialized[:MAX_INTERFACE_DOCUMENT_CHARS]
            selected = {"id": interface_id, "method": method, "path": path, "summary": serialized}
        normalized.append(selected)
        evidence.append({"id": interface_id, "text": serialized})

    total_chars = len(json.dumps(normalized, ensure_ascii=False, default=str))
    if total_chars > MAX_INPUT_CHARS:
        raise BusinessLinkageAnalysisError("接口文档总长度超过安全上限。", code="input_too_large")
    return normalized, evidence


def _evidence_ids(value: Any, valid_ids: set[str], field_name: str) -> list[str]:
    """Validate a non-empty evidence reference list."""
    if not isinstance(value, list) or not value:
        raise BusinessLinkageAnalysisError(f"{field_name} 必须是非空 evidence_ids 数组。")
    result = [str(item).strip() for item in value]
    if any(item not in valid_ids for item in result) or len(result) != len(set(result)):
        raise BusinessLinkageAnalysisError(f"{field_name} 引用了不存在或重复的接口证据。")
    return result


def _validate_linkage_payload(
    payload: Mapping[str, Any],
    *,
    interface_ids: set[str],
    evidence_ids: set[str],
) -> dict[str, Any]:
    """Validate model relations and normalize them to the T051 persistence shape."""
    if not isinstance(payload, Mapping) or not isinstance(payload.get("linkages"), list):
        raise BusinessLinkageAnalysisError("模型输出缺少 linkages 数组。")
    result: list[dict[str, Any]] = []
    seen_linkage_ids: set[str] = set()
    referenced_interfaces: set[str] = set()
    for raw_linkage in payload["linkages"]:
        if not isinstance(raw_linkage, Mapping):
            raise BusinessLinkageAnalysisError("业务链路必须是对象。")
        linkage_id = _safe_identifier(raw_linkage.get("id"), "linkage_id")
        if linkage_id in seen_linkage_ids:
            raise BusinessLinkageAnalysisError("业务链路 id 不能重复。")
        seen_linkage_ids.add(linkage_id)
        name = str(raw_linkage.get("name") or "").strip()
        if not name or len(name) > 200:
            raise BusinessLinkageAnalysisError("业务链路名称不能为空且不能超过 200 个字符。")
        linkage_evidence = _evidence_ids(raw_linkage.get("evidence_ids"), evidence_ids, "链路")
        raw_steps = raw_linkage.get("steps")
        raw_dependencies = raw_linkage.get("dependencies")
        if not isinstance(raw_steps, list) or len(raw_steps) < 2 or not isinstance(raw_dependencies, list) or not raw_dependencies:
            raise BusinessLinkageAnalysisError("业务链路至少需要两个步骤和一条依赖关系。")
        steps: list[dict[str, Any]] = []
        step_ids: set[str] = set()
        orders: set[int] = set()
        for raw_step in raw_steps:
            if not isinstance(raw_step, Mapping):
                raise BusinessLinkageAnalysisError("链路步骤必须是对象。")
            step_id = _safe_identifier(raw_step.get("id"), "step_id")
            interface_id = _safe_identifier(raw_step.get("interface_id"), "interface_id")
            if step_id in step_ids or interface_id not in interface_ids:
                raise BusinessLinkageAnalysisError("步骤 id 不能重复，且 interface_id 必须来自输入接口。")
            try:
                order = int(raw_step.get("order"))
            except (TypeError, ValueError) as exc:
                raise BusinessLinkageAnalysisError("链路步骤 order 必须是正整数。") from exc
            if order < 1 or order in orders:
                raise BusinessLinkageAnalysisError("链路步骤 order 必须从 1 开始且不能重复。")
            step_ids.add(step_id)
            orders.add(order)
            referenced_interfaces.add(interface_id)
            steps.append(
                {
                    "id": step_id,
                    "interface_id": interface_id,
                    "order": order,
                    "purpose": str(raw_step.get("purpose") or "").strip()[:500],
                    "evidence_ids": _evidence_ids(raw_step.get("evidence_ids"), evidence_ids, "步骤"),
                }
            )
        dependencies: list[dict[str, Any]] = []
        dependency_ids: set[str] = set()
        dependency_pairs: set[tuple[str, str]] = set()
        for raw_dependency in raw_dependencies:
            if not isinstance(raw_dependency, Mapping):
                raise BusinessLinkageAnalysisError("链路依赖必须是对象。")
            dependency_id = _safe_identifier(raw_dependency.get("id"), "dependency_id")
            from_step = _safe_identifier(raw_dependency.get("from_step_id"), "from_step_id")
            to_step = _safe_identifier(raw_dependency.get("to_step_id"), "to_step_id")
            pair = (from_step, to_step)
            if dependency_id in dependency_ids or from_step == to_step or from_step not in step_ids or to_step not in step_ids or pair in dependency_pairs:
                raise BusinessLinkageAnalysisError("链路依赖必须引用不同且存在的步骤，且不能重复。")
            dependency_ids.add(dependency_id)
            dependency_pairs.add(pair)
            mappings = raw_dependency.get("data_mappings", [])
            if not isinstance(mappings, list):
                raise BusinessLinkageAnalysisError("data_mappings 必须是数组。")
            dependencies.append(
                {
                    "id": dependency_id,
                    "from_step_id": from_step,
                    "to_step_id": to_step,
                    "data_mappings": [_redact_sensitive(item) for item in mappings[:50]],
                    "evidence_ids": _evidence_ids(raw_dependency.get("evidence_ids"), evidence_ids, "依赖"),
                }
            )
        result.append(
            {
                "id": linkage_id,
                "name": name,
                "description": str(raw_linkage.get("description") or "").strip()[:1000],
                "steps": sorted(steps, key=lambda item: item["order"]),
                "dependencies": dependencies,
                "test_case_ids": [],
                "evidence_ids": linkage_evidence,
            }
        )
    coverage = dict(payload.get("coverage_report") or {}) if isinstance(payload.get("coverage_report"), Mapping) else {}
    coverage["uncovered_interface_ids"] = sorted(interface_ids - referenced_interfaces)
    return {"linkages": result, "coverage_report": coverage}


class BusinessLinkageAnalyzer:
    """Recognize evidence-grounded multi-interface business workflows."""

    def __init__(
        self,
        *,
        runtime_factory: Callable[[ModelConfig], LinkageRuntime] | None = None,
        model_manager: Any | None = None,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        self.runtime_factory = runtime_factory or OpenAICompatibleRuntime
        self.model_manager = model_manager or ModelManager(factory=self.runtime_factory)
        self.prompt_manager = prompt_manager or PromptManager()

    def analyze(
        self,
        *,
        api_documents: Sequence[Mapping[str, Any]],
        project_name: str | None = None,
        preferred_model_name: str | None = None,
    ) -> dict[str, Any]:
        """Return validated business linkages without persisting or executing APIs."""
        documents, evidence = _normalize_interface_documents(api_documents)
        interface_ids = {item["id"] for item in documents}
        evidence_ids = {item["id"] for item in evidence}
        resolved = self.prompt_manager.resolve(
            PromptConfig.SceneType.API_TEST,
            project_name=project_name,
            instant_prompt=LINKAGE_INSTRUCTION,
        )
        text = json.dumps(documents, ensure_ascii=False, sort_keys=True, default=str)
        selected_config: Any = None

        def operation(runtime: LinkageRuntime, config: ModelConfig) -> dict[str, Any]:
            nonlocal selected_config
            selected_config = config
            parameters = getattr(config, "parameters", {})
            parameters = parameters if isinstance(parameters, dict) else {}
            try:
                max_input_chars = max(2000, min(100000, int(parameters.get("structured_input_chars", 24000))))
                max_evidence_items = max(1, min(200, int(parameters.get("structured_segment_items", 32))))
            except (TypeError, ValueError):
                max_input_chars, max_evidence_items = 24000, 32
            segments = plan_structured_segments(
                text,
                evidence,
                max_input_chars=max_input_chars,
                max_evidence_items=max_evidence_items,
            )

            def call_segment(segment: StructuredSegment) -> Mapping[str, Any]:
                payload = runtime.generate_structured(
                    prompt=resolved.content,
                    text=segment.text,
                    evidence=segment.evidence,
                )
                return _validate_linkage_payload(
                    payload,
                    interface_ids={str(item["id"]) for item in segment.evidence},
                    evidence_ids={str(item["id"]) for item in segment.evidence},
                )

            try:
                batch = execute_structured_segments(segments, call_segment)
            except StructuredBatchError as exc:
                partial = exc.partial_payloads[0][1] if exc.partial_payloads else {}
                error_code = next(
                    (
                        str(item.get("error_code"))
                        for item in reversed(exc.trace)
                        if item.get("error_code")
                    ),
                    "structured_generation_error",
                )
                raise BusinessLinkageAnalysisError(
                    "业务链路结构化识别失败，未接受不完整结果。",
                    code=error_code,
                    trace=exc.trace,
                    partial_payload=partial,
                ) from exc
            result = _validate_linkage_payload(
                batch.payload,
                interface_ids=interface_ids,
                evidence_ids=evidence_ids,
            )
            result["coverage_report"]["structured_generation"] = {
                "status": "completed",
                "segment_count": len(batch.trace),
                "completed_segments": len(batch.trace),
                "segments": [dict(item) for item in batch.trace],
            }
            result["coverage_report"]["prompt_provenance"] = {
                "scene_type": PromptConfig.SceneType.API_TEST,
                "layers": list(getattr(resolved, "layers", ())),
                "config_ids": list(getattr(resolved, "config_ids", ())),
                "instant_instruction": True,
            }
            if selected_config is not None:
                result["coverage_report"]["model"] = {
                    "name": getattr(selected_config, "name", ""),
                    "provider": str(getattr(selected_config, "provider", "")),
                    "model_name": getattr(selected_config, "model_name", ""),
                }
            return result

        try:
            return self.model_manager.execute_routed(
                ModelRoutingPolicy.FeatureKey.REQUIREMENT_ANALYSIS,
                operation,
                task_type="business_linkage",
                preferred_name=preferred_model_name,
            )
        except ModelNotFound as exc:
            raise BusinessLinkageAnalysisError(
                "没有可用的业务链路识别模型，请先配置并启用文本结构化模型。",
                code="model_unavailable",
            ) from exc
        except ModelFallbackExhausted as exc:
            cause = exc.last_error
            if isinstance(cause, BusinessLinkageAnalysisError):
                raise cause from exc
            raise BusinessLinkageAnalysisError(
                "业务链路识别模型调用失败，请检查模型路由、网络和模型配置。",
                code="model_error",
            ) from exc


__all__ = ["BusinessLinkageAnalysisError", "BusinessLinkageAnalyzer"]
