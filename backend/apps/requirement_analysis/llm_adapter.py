"""Optional structured model adapter with evidence validation and safe fallback."""

from __future__ import annotations

import json
import base64
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from apps.configs.models import ModelConfig, ModelRoutingPolicy, PromptConfig
from apps.configs.services import (
    ProviderError,
    parse_openai_json_response,
    structured_chat,
)
from core.llm.manager import ModelFallbackExhausted, ModelManager, ModelNotFound
from core.llm.structured_runtime import (
    StructuredBatchError,
    StructuredSegment,
    execute_structured_segments,
    merge_structured_payloads,
    plan_structured_segments,
)
from core.prompts.manager import PromptManager


class StructuredRuntime(Protocol):
    """Runtime contract for a configured provider."""

    def generate_structured(
        self,
        *,
        prompt: str,
        text: str,
        evidence: Sequence[Mapping[str, Any]],
        image_bytes: bytes | None = None,
        image_mime_type: str | None = None,
        preferred_model_name: str | None = None,
    ) -> Mapping[str, Any]: ...


class ModelAnalysisError(RuntimeError):
    """Raised when a model response cannot be safely accepted."""

    def __init__(
        self,
        message: str,
        code: str = "model_error",
        *,
        structured_trace: Sequence[Mapping[str, Any]] = (),
        partial_payload: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.structured_trace = tuple(dict(item) for item in structured_trace)
        self.partial_payload = dict(partial_payload or {})


def _validate_payload(payload: Mapping[str, Any], evidence_ids: set[str], evidence: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Validate model output and reject unsupported or untraceable content."""
    required = ("modules", "functions", "linkages", "test_points")
    if not all(isinstance(payload.get(key), list) for key in required):
        raise ModelAnalysisError("模型输出缺少结构化数组。")
    result = {key: [dict(item) for item in payload[key] if isinstance(item, Mapping)] for key in required}
    seen_ids: set[str] = set()
    for collection in result.values():
        for item in collection:
            item_id = str(item.get("id", "")).strip()
            if not item_id or item_id in seen_ids:
                raise ModelAnalysisError("模型输出包含缺失或重复标识。")
            seen_ids.add(item_id)
            cited = item.get("evidence_ids", [])
            if cited and (not isinstance(cited, list) or not set(map(str, cited)).issubset(evidence_ids)):
                raise ModelAnalysisError("模型输出引用了不存在的证据。")
    source_text = " ".join(str(item.get("text", "")) for item in evidence).strip().casefold()
    if source_text:
        serialized = json.dumps(result, ensure_ascii=False).casefold()
        anchors = set(re.findall(r"[a-z0-9][a-z0-9_-]{2,}", source_text))
        cjk = "".join(re.findall(r"[\u4e00-\u9fff]", source_text))
        anchors.update(cjk[index : index + 2] for index in range(max(0, len(cjk) - 1)))
        if anchors and not any(anchor in serialized for anchor in anchors):
            raise ModelAnalysisError("模型输出与需求证据无可验证关联。")
    coverage = dict(payload.get("coverage_report") or {}) if isinstance(payload.get("coverage_report"), Mapping) else {}
    result["coverage_report"] = coverage
    return result


def _validate_visual_payload(
    payload: Mapping[str, Any],
    evidence_ids: set[str],
    evidence: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Validate a vision response without treating visual inference as fact."""
    required = ("elements", "text_blocks", "regions", "test_points")
    if not all(isinstance(payload.get(key), list) for key in required):
        raise ModelAnalysisError("视觉模型输出缺少结构化数组。", code="invalid_response")
    result = {key: [dict(item) for item in payload[key] if isinstance(item, Mapping)] for key in required}
    seen_ids: set[str] = set()
    for collection in result.values():
        for item in collection:
            item_id = str(item.get("id", "")).strip()
            if not item_id or item_id in seen_ids:
                raise ModelAnalysisError("视觉模型输出包含缺失或重复标识。", code="invalid_response")
            seen_ids.add(item_id)
            cited = item.get("evidence_ids", [])
            if cited and (not isinstance(cited, list) or not set(map(str, cited)).issubset(evidence_ids)):
                raise ModelAnalysisError("视觉模型输出引用了不存在的证据。", code="invalid_response")
    try:
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.0))))
    except (TypeError, ValueError):
        raise ModelAnalysisError("视觉模型输出的置信度无效。", code="invalid_response") from None
    coverage = dict(payload.get("coverage_report") or {}) if isinstance(payload.get("coverage_report"), Mapping) else {}
    warnings = payload.get("warnings", [])
    if isinstance(warnings, list):
        coverage["warnings"] = [str(item) for item in warnings if str(item).strip()]
    coverage["confidence"] = round(confidence, 4)
    coverage["needs_confirmation"] = bool(payload.get("needs_confirmation", confidence < 0.75 or bool(coverage.get("warnings"))))
    result["confidence"] = round(confidence, 4)
    result["needs_confirmation"] = coverage["needs_confirmation"]
    result["coverage_report"] = coverage
    return result


class OpenAICompatibleRuntime:
    """Minimal OpenAI-compatible structured JSON runtime."""

    def __init__(self, config: ModelConfig) -> None:
        self.config = config

    def generate_structured(
        self,
        *,
        prompt: str,
        text: str,
        evidence: Sequence[Mapping[str, Any]],
        image_bytes: bytes | None = None,
        image_mime_type: str | None = None,
    ) -> Mapping[str, Any]:
        """Call a configured provider without logging credentials or source content."""
        parameters = self.config.parameters if isinstance(self.config.parameters, dict) else {}
        try:
            configured_limit = parameters.get(
                "structured_max_tokens",
                parameters.get("max_tokens", 8192),
            )
            max_tokens = max(512, min(8192, int(configured_limit)))
        except (TypeError, ValueError):
            max_tokens = 8192
        user_payload = json.dumps({"text": text, "evidence": list(evidence)}, ensure_ascii=False)
        user_content: str | list[dict[str, Any]] = user_payload
        if image_bytes:
            encoded = base64.b64encode(image_bytes).decode("ascii")
            mime_type = image_mime_type or "image/png"
            user_content = [
                {"type": "text", "text": user_payload},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
            ]
        try:
            response = structured_chat(
                self.config,
                messages=(
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ),
                max_tokens=max_tokens,
                temperature=float(parameters.get("structured_temperature", 0)),
            )
            return parse_openai_json_response(response)
        except ProviderError as exc:
            raise ModelAnalysisError(str(exc), code=exc.code) from exc


class RequirementModelAdapter:
    """Route requirement analysis through configured models with fallback."""

    def __init__(self, *, runtime_factory: Callable[[ModelConfig], StructuredRuntime] | None = None, model_manager: ModelManager | None = None, prompt_manager: PromptManager | None = None) -> None:
        self.runtime_factory = runtime_factory or OpenAICompatibleRuntime
        self.model_manager = model_manager or ModelManager(factory=self.runtime_factory)
        self.prompt_manager = prompt_manager or PromptManager()

    def analyze(
        self,
        *,
        text: str,
        evidence: Sequence[Mapping[str, Any]],
        project_name: str | None = None,
        task_type: str = "requirement_analysis",
        scene_type: str = PromptConfig.SceneType.REQUIREMENT_ANALYSIS,
        image_bytes: bytes | None = None,
        image_mime_type: str | None = None,
        preferred_model_name: str | None = None,
    ) -> dict[str, Any]:
        """Return validated model output or raise a safe, retryable error."""
        evidence_ids = {str(item.get("id")) for item in evidence if item.get("id")}
        return self.run(
            text=text,
            evidence=evidence,
            project_name=project_name,
            task_type=task_type,
            scene_type=scene_type,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
            preferred_model_name=preferred_model_name,
            validator=lambda payload: _validate_payload(payload, evidence_ids, evidence),
        )

    def analyze_visual(
        self,
        *,
        text: str,
        evidence: Sequence[Mapping[str, Any]],
        image_bytes: bytes,
        image_mime_type: str,
        project_name: str | None = None,
        preferred_model_name: str | None = None,
    ) -> dict[str, Any]:
        """Run an evidence-grounded multimodal analysis through the shared runtime."""
        evidence_ids = {str(item.get("id")) for item in evidence if item.get("id")}
        instruction = (
            "只输出 JSON；区分图像中直接可见的事实和需要人工确认的推断。"
            "识别 elements、text_blocks、regions、test_points，并为可追溯内容填写 evidence_ids。"
            "无法从图像确认的交互、业务含义或错误原因必须标记 needs_confirmation。"
            "Output ONLY a JSON object with top-level keys elements, text_blocks, regions, test_points, confidence, warnings, needs_confirmation, coverage_report."
        )
        result = self.run(
            text=text,
            evidence=evidence,
            project_name=project_name,
            task_type="screenshot",
            scene_type=PromptConfig.SceneType.SCREENSHOT_ANALYSIS,
            instant_prompt=instruction,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
            preferred_model_name=preferred_model_name,
            validator=lambda payload: _validate_visual_payload(payload, evidence_ids, evidence),
        )
        coverage = dict(result.get("coverage_report") or {})
        result["warnings"] = list(coverage.get("warnings") or [])
        result["confidence"] = float(coverage.get("confidence", result.get("confidence", 0.0)) or 0.0)
        result["needs_confirmation"] = bool(coverage.get("needs_confirmation", True))
        result["method"] = "model_verified_visual"
        return result

    def run(
        self,
        *,
        text: str,
        evidence: Sequence[Mapping[str, Any]],
        project_name: str | None = None,
        task_type: str = "requirement_analysis",
        scene_type: str = PromptConfig.SceneType.REQUIREMENT_ANALYSIS,
        validator: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
        instant_prompt: str | None = None,
        prompt_override: str | None = None,
        image_bytes: bytes | None = None,
        image_mime_type: str | None = None,
        preferred_model_name: str | None = None,
        segment_builder: Callable[[str, Sequence[Mapping[str, Any]], int, int], Sequence[StructuredSegment]] | None = None,
    ) -> dict[str, Any]:
        """Execute bounded structured segments and apply a caller validator."""
        evidence_ids = {str(item.get("id")) for item in evidence if item.get("id")}
        instruction = instant_prompt or (
            "只输出 JSON。modules 中每个对象必须包含可读的非空 name；functions 中每个对象必须包含可读的非空 name 和 description；test_points 中每个对象必须包含可读的非空 description；"
            "modules、functions、linkages、test_points 中的每一个对象都必须包含非空 evidence_ids 数组，"
            "functions 中每个对象必须通过 module_id 关联 modules 中已输出的模块，test_points 中每个对象必须通过 function_id 关联 functions 中已输出的功能点；"
            "联动测试点必须通过 scenario_id 关联 linkages 中的场景，linkages 的 from/to 必须关联已输出的功能点。"
            "每个 test_points 对象必须填写 type，且只能使用 positive（正向）、negative（异常）、boundary（边界）、security（安全）、linkage（联动）、performance（性能）之一。"
            "数组中的每个 ID 必须来自当前输入的 evidence.id；没有证据支持的对象不要生成，不能留空或省略该字段。"
            "本段提供的每一条 evidence 都必须至少被一个输出对象引用；无法归类的证据写入 coverage_report.uncovered_evidence_ids，"
            "不要用虚构内容填充。无法确认的内容放入 needs_confirmation。 "
            "Output ONLY a JSON object with top-level keys modules, functions, linkages, test_points, coverage_report. "
            "The first four keys MUST be arrays of objects; every item MUST have a unique string id. "
            "Every function MUST have a valid module_id and every non-linkage test point MUST have a valid function_id. "
            "Every linkage test point MUST have a valid scenario_id and every linkage MUST reference valid function ids. "
            "Every module and function MUST have a non-empty human-readable name, and every test point MUST have a non-empty description. "
            "Every test point MUST have exactly one type from positive, negative, boundary, security, linkage, performance. "
            "Every item MUST contain at least one valid evidence_ids value. "
            "Use only evidence_ids present in the input, do not echo the input text/evidence, and do not use Markdown."
        )
        resolved = self.prompt_manager.resolve(
            scene_type,
            project_name=project_name,
            instant_prompt=instruction,
        )
        prompt_content = prompt_override.strip() if isinstance(prompt_override, str) and prompt_override.strip() else resolved.content
        feature_key = {
            "screenshot": ModelRoutingPolicy.FeatureKey.SCREENSHOT_ANALYSIS,
            "case_gen": ModelRoutingPolicy.FeatureKey.CASE_GENERATION,
            "case_review": ModelRoutingPolicy.FeatureKey.CASE_REVIEW,
        }.get(task_type, ModelRoutingPolicy.FeatureKey.REQUIREMENT_ANALYSIS)
        resolved_route = None
        selected_config = None
        if isinstance(self.model_manager, ModelManager):
            try:
                resolved_route = self.model_manager.resolve_route(
                    feature_key,
                    task_type=task_type,
                    preferred_name=preferred_model_name,
                )
            except Exception:
                # The routed execution below remains the source of truth.  A
                # diagnostic lookup must never hide its original error.
                resolved_route = None

        def route_metadata() -> dict[str, Any]:
            """Return safe metadata for the configuration that actually ran."""
            if not isinstance(self.model_manager, ModelManager):
                return {}
            config = selected_config or (resolved_route.primary.config if resolved_route and resolved_route.primary else None)
            if config is None:
                return resolved_route.as_dict() if resolved_route else {"available": False}
            source = ""
            if resolved_route:
                candidate = next((item for item in resolved_route.candidates if item.config.pk == config.pk), None)
                source = candidate.source if candidate else "operation"
            return {
                "feature_key": feature_key,
                "available": True,
                "effective_source": source,
                "model": {
                    "id": config.pk,
                    "name": config.name,
                    "provider": config.provider,
                    "model_name": config.model_name,
                    "model_type": config.model_type,
                },
                "candidates": [item.as_dict() for item in resolved_route.candidates] if resolved_route else [],
            }

        def operation(runtime: StructuredRuntime, config: ModelConfig) -> dict[str, Any]:
            nonlocal selected_config
            selected_config = config
            raw_parameters = getattr(config, "parameters", {})
            parameters = raw_parameters if isinstance(raw_parameters, dict) else {}
            try:
                max_input_chars = max(2000, min(100000, int(parameters.get("structured_input_chars", 24000))))
                max_evidence_items = max(1, min(200, int(parameters.get("structured_segment_items", 32))))
            except (TypeError, ValueError):
                max_input_chars, max_evidence_items = 24000, 32
            segments = tuple(
                segment_builder(text, evidence, max_input_chars, max_evidence_items)
                if segment_builder
                else plan_structured_segments(
                    text,
                    evidence,
                    max_input_chars=max_input_chars,
                    max_evidence_items=max_evidence_items,
                )
            )
            if not segments:
                raise ModelAnalysisError("结构化调用没有可执行的输入分段。", code="empty_segments")

            def call_segment(segment: StructuredSegment) -> Mapping[str, Any]:
                segment_prompt = prompt_content
                if len(segments) > 1 or segment.depth:
                    segment_prompt += (
                        "\n当前是结构化分段生成。只处理本段提供的正文和证据，不要假设其他分段内容；"
                        f"本段编号为 {segment.segment_id}，输出仍必须是符合 Schema 的 JSON 对象。"
                    )
                payload = runtime.generate_structured(
                    prompt=segment_prompt,
                    text=segment.text,
                    evidence=segment.evidence,
                    image_bytes=image_bytes,
                    image_mime_type=image_mime_type,
                )
                return validator(payload) if validator else dict(payload)

            try:
                batch = execute_structured_segments(segments, call_segment)
            except StructuredBatchError as exc:
                error_code = next(
                    (str(item.get("error_code")) for item in reversed(exc.trace) if item.get("error_code")),
                    "structured_generation_error",
                )
                partial_payload = merge_structured_payloads(exc.partial_payloads)
                partial_coverage = dict(partial_payload.get("coverage_report") or {})
                partial_coverage["structured_generation"] = {
                    "status": "partial",
                    "segment_count": len(segments),
                    "completed_segments": len(exc.partial_payloads),
                    "segments": [dict(item) for item in exc.trace],
                }
                partial_coverage["prompt_provenance"] = {
                    "scene_type": scene_type,
                    "layers": list(getattr(resolved, "layers", ())),
                    "config_ids": list(getattr(resolved, "config_ids", ())),
                    "instant_instruction": bool(instant_prompt),
                }
                partial_coverage["model_route"] = route_metadata()
                partial_payload["coverage_report"] = partial_coverage
                raise ModelAnalysisError(
                    f"{exc} 已完成 {len(exc.partial_payloads)} 个分段，失败段可按轨迹恢复。",
                    code=error_code,
                    structured_trace=exc.trace,
                    partial_payload=partial_payload,
                ) from exc
            result = batch.payload
            if validator:
                result = validator(result)
            coverage = dict(result.get("coverage_report") or {})
            coverage["structured_generation"] = {
                "status": "completed",
                "segment_count": len(batch.trace),
                "completed_segments": sum(item.get("status") == "completed" for item in batch.trace),
                "segments": [dict(item) for item in batch.trace],
            }
            coverage["prompt_provenance"] = {
                "scene_type": scene_type,
                "layers": list(getattr(resolved, "layers", ())),
                "config_ids": list(getattr(resolved, "config_ids", ())),
                "instant_instruction": bool(instant_prompt),
            }
            coverage["model_route"] = route_metadata()
            result["coverage_report"] = coverage
            return result
        try:
            # Production managers always use the explicit route resolver. The
            # legacy branch is retained only for small injected test doubles.
            if self.model_manager.__class__.__module__ == "core.llm.manager":
                return self.model_manager.execute_routed(
                    feature_key,
                    operation,
                    task_type=task_type,
                    preferred_name=preferred_model_name,
                )
            return self.model_manager.execute_with_fallback(task_type, operation, retry_on=(Exception,))
        except ModelNotFound as exc:
            raise ModelAnalysisError(
                "没有可用的需求分析模型，请先配置并启用兼容文本分析的模型。"
            ) from exc
        except ModelFallbackExhausted as exc:
            attempted = "、".join(exc.attempted_models) or "未记录"
            cause = exc.last_error or exc.__cause__
            if isinstance(cause, ModelAnalysisError):
                cause.args = (f"{cause} \u5df2\u5c1d\u8bd5\u6a21\u578b\uff1a{attempted}",)
                raise cause from exc
            error_code = cause.code if isinstance(cause, ModelAnalysisError) else "model_error"
            structured_trace = cause.structured_trace if isinstance(cause, ModelAnalysisError) else ()
            partial_payload = cause.partial_payload if isinstance(cause, ModelAnalysisError) else {}
            detail = f" {cause}" if isinstance(cause, ModelAnalysisError) and str(cause) else ""
            raise ModelAnalysisError(
                f"需求分析模型调用失败，已尝试模型：{attempted}。{detail}"
                "请检查 API 地址、模型名称、Key、网络和模型路由。"
            ) from exc


__all__ = ["ModelAnalysisError", "OpenAICompatibleRuntime", "RequirementModelAdapter", "StructuredRuntime"]
