"""Optional structured model adapter with evidence validation and safe fallback."""

from __future__ import annotations

import json
import base64
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from apps.configs.models import ModelConfig, ModelRoutingPolicy, PromptConfig
from apps.configs.services import canonical_base
from core.llm.manager import ModelFallbackExhausted, ModelManager, ModelNotFound
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
        try:
            base = canonical_base(self.config.provider, self.config.api_base_url)
        except (KeyError, ValueError) as exc:
            raise ModelAnalysisError("模型未配置有效 API 基础地址。") from exc
        token = self.config.get_api_key() if self.config.api_key_encrypted else ""
        parameters = self.config.parameters if isinstance(self.config.parameters, dict) else {}
        try:
            max_tokens = max(128, min(8192, int(parameters.get("max_tokens", 2048))))
        except (TypeError, ValueError):
            max_tokens = 2048
        user_payload = json.dumps({"text": text, "evidence": list(evidence)}, ensure_ascii=False)
        user_content: str | list[dict[str, Any]] = user_payload
        if image_bytes:
            encoded = base64.b64encode(image_bytes).decode("ascii")
            mime_type = image_mime_type or "image/png"
            user_content = [
                {"type": "text", "text": user_payload},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
            ]
        body = {
            "model": self.config.model_name,
            "temperature": parameters.get("structured_temperature", 0),
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ],
        }
        # DeepSeek reasoning models can spend the entire output budget in
        # ``reasoning_content`` and leave ``message.content`` empty.  Structured
        # analysis requires the final JSON channel, so disable thinking by
        # default while still allowing an explicit provider setting.
        if self.config.provider.lower() == "deepseek":
            thinking = parameters.get("thinking", {"type": "disabled"})
            if isinstance(thinking, str):
                thinking = {"type": thinking}
            if isinstance(thinking, Mapping):
                body["thinking"] = dict(thinking)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if token:
            if self.config.provider == "anthropic":
                headers.update({"x-api-key": token, "anthropic-version": "2023-06-01"})
            elif self.config.provider == "google":
                headers["x-goog-api-key"] = token
            elif self.config.provider == "azure":
                headers["api-key"] = token
            else:
                headers["Authorization"] = f"Bearer {token}"
        request = Request(f"{base}/chat/completions", data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
        try:
            with urlopen(request, timeout=30) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise ModelAnalysisError("模型调用失败，已进入安全降级。") from exc
        try:
            content = raw["choices"][0]["message"].get("content")
            if isinstance(content, str):
                normalized = content.strip()
                if normalized.startswith("```"):
                    normalized = normalized.strip("`").removeprefix("json").strip()
                return json.loads(normalized)
            if isinstance(content, list):
                text_parts = [item.get("text", "") for item in content if isinstance(item, Mapping)]
                normalized = "".join(part for part in text_parts if isinstance(part, str)).strip()
                if normalized:
                    return json.loads(normalized)
            return content
        except (AttributeError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ModelAnalysisError("模型返回不是有效 JSON 结构。") from exc


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
    ) -> dict[str, Any]:
        """Execute a structured runtime and apply a caller-provided validator."""
        evidence_ids = {str(item.get("id")) for item in evidence if item.get("id")}
        instruction = instant_prompt or (
            "只输出 JSON；每个功能和测试点必须引用可验证 evidence_ids；无法确认的内容放入 needs_confirmation。 "
            "Output ONLY a JSON object with top-level keys modules, functions, linkages, test_points, coverage_report. "
            "The first four keys MUST be arrays of objects; every item MUST have a unique string id. "
            "Use only evidence_ids present in the input, do not echo the input text/evidence, and do not use Markdown."
        )
        resolved = self.prompt_manager.resolve(
            scene_type,
            project_name=project_name,
            instant_prompt=instruction,
        )
        prompt_content = prompt_override.strip() if isinstance(prompt_override, str) and prompt_override.strip() else resolved.content
        def operation(runtime: StructuredRuntime, _config: ModelConfig) -> dict[str, Any]:
            payload = runtime.generate_structured(
                prompt=prompt_content,
                text=text,
                evidence=evidence,
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
            )
            return validator(payload) if validator else dict(payload)
        try:
            feature_key = {
                "screenshot": ModelRoutingPolicy.FeatureKey.SCREENSHOT_ANALYSIS,
                "case_gen": ModelRoutingPolicy.FeatureKey.CASE_GENERATION,
                "case_review": ModelRoutingPolicy.FeatureKey.CASE_REVIEW,
            }.get(task_type, ModelRoutingPolicy.FeatureKey.REQUIREMENT_ANALYSIS)
            use_routed_policy = bool(preferred_model_name)
            if self.model_manager.__class__.__module__ == "core.llm.manager":
                use_routed_policy = use_routed_policy or ModelRoutingPolicy.objects.filter(
                    feature_key__in=(ModelRoutingPolicy.FeatureKey.GLOBAL, feature_key),
                    is_active=True,
                ).exists()
            if use_routed_policy:
                return self.model_manager.execute_routed(
                    feature_key,
                    operation,
                    task_type=task_type,
                    preferred_name=preferred_model_name,
                )
            return self.model_manager.execute_with_fallback(task_type, operation, retry_on=(Exception,))
        except (ModelNotFound, ModelFallbackExhausted) as exc:
            raise ModelAnalysisError("没有可用的需求分析模型，已使用确定性基线。") from exc


__all__ = ["ModelAnalysisError", "OpenAICompatibleRuntime", "RequirementModelAdapter", "StructuredRuntime"]
