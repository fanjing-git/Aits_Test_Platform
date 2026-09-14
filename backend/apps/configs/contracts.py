"""Shared model-call contracts and capability requirements."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from apps.configs.models import ModelConfig


class ModelCapabilityError(ValueError):
    """Raised before a model call when the selected capability is incompatible."""

    def __init__(self, message: str, code: str = "model_capability_mismatch") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ModelCallContract:
    """Describe the input, output, and model capabilities required by one feature."""

    feature_key: str
    capability: str
    label: str
    accepted_model_types: tuple[str, ...]
    input_mode: str
    output_mode: str
    requires_model: bool = True
    structured_output: bool = True

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe contract for REST and frontend diagnostics."""
        data = asdict(self)
        data["accepted_model_types"] = [
            str(getattr(item, "value", item)) for item in self.accepted_model_types
        ]
        return data


TEXT_MODEL_TYPES = (
    ModelConfig.ModelType.CHAT,
    ModelConfig.ModelType.MULTIMODAL,
    ModelConfig.ModelType.VISION,
)

_FEATURE_ALIASES = {
    "requirement": "requirement_analysis",
    "case_gen": "case_generation",
    "screenshot": "screenshot_analysis",
    "vision": "screenshot_analysis",
    "agent": "agent_execution",
    "report": "report_generation",
    "knowledge": "knowledge_model",
    "embedding": "knowledge_model",
    "vectorization": "knowledge_model",
    "indexing": "knowledge_model",
    "retrieval": "knowledge_model",
}

CAPABILITY_CONTRACTS: dict[str, ModelCallContract] = {
    "global": ModelCallContract(
        "global", "configuration", "平台模型配置", tuple(choice.value for choice in ModelConfig.ModelType),
        "provider_metadata", "configuration", requires_model=False, structured_output=False,
    ),
    "requirement_analysis": ModelCallContract(
        "requirement_analysis", "text_structured", "需求深度分析", TEXT_MODEL_TYPES,
        "text", "json_object",
    ),
    "case_generation": ModelCallContract(
        "case_generation", "text_structured", "测试用例生成", TEXT_MODEL_TYPES,
        "text", "json_object",
    ),
    "case_review": ModelCallContract(
        "case_review", "text_structured", "测试用例评审", TEXT_MODEL_TYPES,
        "text", "json_object",
    ),
    "agent_execution": ModelCallContract(
        "agent_execution", "text_structured", "智能体执行", TEXT_MODEL_TYPES,
        "text_and_tools", "json_object",
    ),
    "report_generation": ModelCallContract(
        "report_generation", "text_structured", "报告生成", TEXT_MODEL_TYPES,
        "text", "json_object",
    ),
    "screenshot_analysis": ModelCallContract(
        "screenshot_analysis", "vision_structured", "截图与视觉分析",
        (ModelConfig.ModelType.VISION, ModelConfig.ModelType.MULTIMODAL),
        "text_and_image", "json_object",
    ),
    "knowledge_model": ModelCallContract(
        "knowledge_model", "embedding_or_rerank", "知识库模型任务",
        (ModelConfig.ModelType.EMBEDDING, ModelConfig.ModelType.RERANK),
        "text_or_documents", "vectors_or_ranked_documents",
    ),
}

_TASK_ALIASES = {
    "embedding": "knowledge_model",
    "vectorization": "knowledge_model",
    "indexing": "knowledge_model",
    "retrieval": "knowledge_model",
    "vision": "screenshot_analysis",
    "image_analysis": "screenshot_analysis",
    "screenshot": "screenshot_analysis",
}

_MODEL_TYPE_LABELS = dict(ModelConfig.ModelType.choices)


def normalize_contract_feature(feature_key: str | None) -> str:
    """Normalize a feature alias without importing the routing layer."""
    value = (feature_key or "global").strip().lower().replace("-", "_")
    return _FEATURE_ALIASES.get(value, value)


def model_call_contract(feature_key: str | None, task_type: str | None = None) -> ModelCallContract:
    """Resolve one stable call contract from a feature and optional task type."""
    task = (task_type or "").strip().lower().replace("-", "_")
    if task in {"embedding", "vectorization", "indexing", "retrieval"}:
        return ModelCallContract(
            "knowledge_model", "embedding", "Embedding 任务",
            (ModelConfig.ModelType.EMBEDDING,), "text_or_documents", "vectors",
        )
    if task in {"vision", "screenshot", "image_analysis"}:
        return CAPABILITY_CONTRACTS["screenshot_analysis"]
    if task in {choice.value for choice in ModelConfig.ModelType}:
        if task == ModelConfig.ModelType.MULTIMODAL:
            return CAPABILITY_CONTRACTS["screenshot_analysis"]
        return ModelCallContract(
            task,
            task,
            _MODEL_TYPE_LABELS.get(task, task),
            (task,),
            "specialized_input",
            "provider_result",
            structured_output=False,
        )
    normalized = _TASK_ALIASES.get(task, normalize_contract_feature(feature_key))
    return CAPABILITY_CONTRACTS.get(normalized, CAPABILITY_CONTRACTS["requirement_analysis"])


def validate_model_capability(config: ModelConfig, contract: ModelCallContract) -> None:
    """Reject inactive or capability-incompatible configurations before execution."""
    if not config.is_active:
        raise ModelCapabilityError("所选模型已停用，请重新选择启用的模型。", "model_inactive")
    if config.model_type not in contract.accepted_model_types:
        raise ModelCapabilityError(
            f"{contract.label}需要 {contract.capability} 能力，当前模型类型不匹配。"
        )
