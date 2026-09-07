"""Provider metadata and conservative model capability normalization.

The local selection is a documented fallback, never an exhaustive account list.
Live discovery retains every model, including IDs whose capabilities are unknown.
"""

from copy import deepcopy
from typing import Any

from apps.configs.models import ModelConfig


TYPE_LABELS = dict(ModelConfig.ModelType.choices)
TYPE_LABELS["chat"] = "文本对话与推理"
TYPE_LABELS["vision"] = "图像 / 视频理解"

PROVIDERS = {
    "openai": ("OpenAI", "https://api.openai.com/v1", "https://platform.openai.com/docs/models"),
    "anthropic": ("Anthropic", "https://api.anthropic.com/v1", "https://platform.claude.com/docs/en/api/models/list"),
    "google": ("Google Gemini", "https://generativelanguage.googleapis.com/v1beta", "https://ai.google.dev/api/models"),
    "qwen": ("阿里云百炼 / 通义千问", "https://dashscope.aliyuncs.com/compatible-mode/v1", "https://help.aliyun.com/zh/model-studio/models"),
    "baidu": ("百度千帆", "https://qianfan.baidubce.com/v2", "https://cloud.baidu.com/doc/qianfan-api/s/Dmba8k71y"),
    "deepseek": ("DeepSeek", "https://api.deepseek.com", "https://api-docs.deepseek.com/api/list-models"),
    "zhipu": ("智谱", "https://open.bigmodel.cn/api/paas/v4", "https://docs.bigmodel.cn/cn/guide/start/model-overview"),
    "azure": ("Azure OpenAI", "", "https://learn.microsoft.com/en-us/rest/api/aifoundry/azureopenai/models"),
    "custom": ("OpenAI 兼容", "", ""),
    "local": ("Ollama / vLLM", "http://127.0.0.1:11434/v1", "https://docs.ollama.com/api/tags"),
}

# Official reference snapshot checked 2026-09-07. Live account results replace it.
REFERENCE_MODELS = {
    "openai": {
        "chat": ["gpt-4.1", "gpt-4o", "gpt-4o-mini"],
        "vision": ["gpt-4.1", "gpt-4o", "gpt-4o-mini"],
        "embedding": ["text-embedding-3-small", "text-embedding-3-large"],
    },
    "anthropic": {
        "chat": ["claude-fable-5-1", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"],
        "vision": ["claude-fable-5-1", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"],
    },
    "google": {
        "chat": ["gemini-2.5-pro", "gemini-2.5-flash"],
        "vision": ["gemini-2.5-pro", "gemini-2.5-flash"],
    },
    "deepseek": {"chat": ["deepseek-v4-pro", "deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"]},
    "zhipu": {
        "chat": ["glm-5", "glm-5.2"],
        "embedding": ["embedding-3"],
        "audio": ["glm-4-voice"],
        "image_generation": ["cogview-4-250304"],
    },
    "baidu": {"chat": ["ernie-4.5-turbo-32k", "ernie-speed-128k"]},
    "qwen": {
        "chat": ["qwen3.8-max", "qwen3.7-plus", "qwen3.8-flash", "deepseek-v4-pro", "deepseek-v4-flash-0731", "kimi-k3", "glm-5.2", "MiniMax-M3", "mimo-v2.5-pro"],
        "vision": ["qwen3.8-max", "qwen3.7-plus", "qwen3.5-omni-plus"],
        "image_generation": ["qwen-image-3.0-pro", "wan2.7-image-pro"],
        "video": ["happyhorse-1.1-t2v", "happyhorse-1.1-i2v", "happyhorse-1.1-r2v", "happyhorse-1.0-video-edit", "wan3.0-video"],
        "tts": ["qwen-audio-3.0-tts-plus", "MiniMax/speech-2.8-hd"],
        "asr": ["qwen-audio-3.0-asr-flash-streaming", "qwen-audio-3.0-asr-flash-filetrans"],
        "multimodal": ["qwen3.5-omni-plus", "qwen3.5-omni-plus-realtime"],
        "realtime": ["qwen-audio-3.0-realtime-plus", "qwen3.5-omni-plus-realtime"],
        "audio": ["fun-music-v1"],
        "embedding": ["text-embedding-v4", "qwen3.7-text-embedding", "tongyi-embedding-vision-plus"],
        "rerank": ["qwen3-rerank"],
        "three_d": ["Tripo/Tripo-H3.1", "Tripo/Tripo-P1.0"],
    },
}

PROVIDER_TYPES = {
    "anthropic": {"chat", "vision", "other"},
    "deepseek": {"chat", "vision", "other"},
    "google": {"chat", "vision", "embedding", "image_generation", "video", "audio", "tts", "realtime", "multimodal", "other"},
}

CAPABILITY_TYPES = {
    "TG": "chat", "Reasoning": "chat", "VU": "vision", "IG": "image_generation",
    "VG": "video", "ASR": "asr", "TTS": "tts", "TR": "embedding", "ME": "embedding",
    "Multimodal-Omni": "multimodal", "Realtime-Omni": "realtime",
    "Realtime-Text-to-Speech": "realtime", "Realtime-ASR": "realtime",
    "Realtime-Audio-Translate": "realtime", "Realtime-Chatting": "realtime",
    "3D-generation": "three_d",
}


def normalize_model(item: dict[str, Any], provider: str) -> dict[str, Any]:
    """Keep provider IDs intact and prefer declared capabilities over guesses."""
    identifier = item.get("id") or item.get("model") or item.get("name")
    if not isinstance(identifier, str) or not identifier or len(identifier) > 200:
        raise ValueError("模型目录包含无效模型编号。")
    if provider == "google" and identifier.startswith("models/"):
        identifier = identifier[7:]
    capabilities = item.get("capabilities", [])
    if not isinstance(capabilities, list):
        capabilities = []
    types = {CAPABILITY_TYPES[c] for c in capabilities if isinstance(c, str) and c in CAPABILITY_TYPES}
    methods = item.get("supportedGenerationMethods", [])
    if isinstance(methods, list):
        if "embedContent" in methods:
            types.add("embedding")
        if "generateContent" in methods:
            types.add("chat")
    for kind, names in REFERENCE_MODELS.get(provider, {}).items():
        if identifier in names:
            types.add(kind)
    # Anthropic's Models API enumerates Claude message models, all vision capable.
    if provider == "anthropic":
        types.update(("chat", "vision"))
    display = item.get("display_name") or item.get("displayName") or item.get("name") or identifier
    return {"id": identifier, "label": str(display)[:200], "types": sorted(types) or ["other"],
            "capabilities": [c[:80] for c in capabilities if isinstance(c, str)][:30]}


def provider_catalog() -> list[dict[str, Any]]:
    """Return all supported capability choices and clearly labelled references."""
    result = []
    for provider, (label, base_url, source) in PROVIDERS.items():
        entries: dict[str, dict[str, Any]] = {}
        for kind, names in REFERENCE_MODELS.get(provider, {}).items():
            for name in names:
                entry = entries.setdefault(name, {"id": name, "label": name, "types": []})
                entry["types"].append(kind)
        result.append({"value": provider, "label": label, "default_base_url": base_url,
                       "source_url": source, "source": "reference", "updated_at": "2026-09-07",
                       "complete": False, "models": list(entries.values()),
                       "types": [{"value": key, "label": name, "models": deepcopy(REFERENCE_MODELS.get(provider, {}).get(key, []))}
                                 for key, name in TYPE_LABELS.items()
                                 if key in PROVIDER_TYPES.get(provider, TYPE_LABELS)]})
    return result
