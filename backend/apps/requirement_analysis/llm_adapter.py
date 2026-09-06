"""Optional structured model adapter with evidence validation and safe fallback."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from apps.configs.models import ModelConfig, PromptConfig
from core.llm.manager import ModelFallbackExhausted, ModelManager, ModelNotFound
from core.prompts.manager import PromptManager


class StructuredRuntime(Protocol):
    """Runtime contract for a configured provider."""

    def generate_structured(self, *, prompt: str, text: str, evidence: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]: ...


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

    def generate_structured(self, *, prompt: str, text: str, evidence: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        """Call a configured provider without logging credentials or source content."""
        base = self.config.api_base_url.strip().rstrip("/")
        if not base:
            base = {"openai": "https://api.openai.com/v1", "deepseek": "https://api.deepseek.com/v1", "local": "http://127.0.0.1:11434/v1"}.get(self.config.provider, "")
        if not base:
            raise ModelAnalysisError("模型未配置 API 基础地址。")
        token = self.config.get_api_key() if self.config.api_key_encrypted else ""
        parameters = self.config.parameters if isinstance(self.config.parameters, dict) else {}
        try:
            max_tokens = max(128, min(8192, int(parameters.get("max_tokens", 2048))))
        except (TypeError, ValueError):
            max_tokens = 2048
        body = {
            "model": self.config.model_name,
            "temperature": parameters.get("temperature", 0),
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps({"text": text, "evidence": list(evidence)}, ensure_ascii=False)},
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
        request = Request(f"{base}/chat/completions", data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers={"Accept": "application/json", "Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}, method="POST")
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

    def analyze(self, *, text: str, evidence: Sequence[Mapping[str, Any]], project_name: str | None = None, task_type: str = "requirement_analysis", scene_type: str = PromptConfig.SceneType.REQUIREMENT_ANALYSIS) -> dict[str, Any]:
        """Return validated model output or raise a safe, retryable error."""
        evidence_ids = {str(item.get("id")) for item in evidence if item.get("id")}
        return self.run(text=text, evidence=evidence, project_name=project_name, task_type=task_type, scene_type=scene_type, validator=lambda payload: _validate_payload(payload, evidence_ids, evidence))

    def run(self, *, text: str, evidence: Sequence[Mapping[str, Any]], project_name: str | None = None, task_type: str = "requirement_analysis", scene_type: str = PromptConfig.SceneType.REQUIREMENT_ANALYSIS, validator: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None) -> dict[str, Any]:
        """Execute a structured runtime and apply a caller-provided validator."""
        evidence_ids = {str(item.get("id")) for item in evidence if item.get("id")}
        resolved = self.prompt_manager.resolve(
            scene_type,
            project_name=project_name,
            instant_prompt=(
                "只输出 JSON；每个功能和测试点必须引用可验证 evidence_ids；无法确认的内容放入 needs_confirmation。 "
                "Output ONLY a JSON object with top-level keys modules, functions, linkages, test_points, coverage_report. "
                "The first four keys MUST be arrays of objects; every item MUST have a unique string id. "
                "Use only evidence_ids present in the input, do not echo the input text/evidence, and do not use Markdown."
            ),
        )
        def operation(runtime: StructuredRuntime, _config: ModelConfig) -> dict[str, Any]:
            payload = runtime.generate_structured(prompt=resolved.content, text=text, evidence=evidence)
            return validator(payload) if validator else dict(payload)
        try:
            return self.model_manager.execute_with_fallback(task_type, operation, retry_on=(Exception,))
        except (ModelNotFound, ModelFallbackExhausted) as exc:
            raise ModelAnalysisError("没有可用的需求分析模型，已使用确定性基线。") from exc


__all__ = ["ModelAnalysisError", "OpenAICompatibleRuntime", "RequirementModelAdapter", "StructuredRuntime"]
