"""Safe extension contracts for model configuration operations."""

from dataclasses import dataclass
from typing import Protocol
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request as UrlRequest, urlopen

from apps.configs.models import ModelConfig


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    """Provider-neutral result returned by a connection adapter."""

    ok: bool
    message: str
    latency_ms: int | None = None


class ConnectionTester(Protocol):
    def test(self, config: ModelConfig) -> ConnectionTestResult: ...


class ProviderConnectionTester:
    """Perform a safe, short model-list probe against the configured endpoint."""

    DEFAULT_BASE_URLS = {
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com/v1",
        "google": "https://generativelanguage.googleapis.com/v1beta",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "baidu": "https://qianfan.baidubce.com/v2",
        "deepseek": "https://api.deepseek.com",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4",
        "azure": "",
    }

    def test(self, config: ModelConfig) -> ConnectionTestResult:
        base_url = config.api_base_url or self.DEFAULT_BASE_URLS.get(config.provider, "")
        if not base_url:
            return ConnectionTestResult(False, "请先填写 API 地址。")
        if config.provider not in {"local", "custom"} and not config.get_api_key():
            return ConnectionTestResult(False, "该供应商需要配置 API Key。")
        endpoint = base_url.rstrip("/")
        if not endpoint.endswith("/models"):
            endpoint = f"{endpoint}/models"
        headers = {"Accept": "application/json"}
        api_key = config.get_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            headers["api-key"] = api_key
        started = monotonic()
        try:
            request = UrlRequest(endpoint, headers=headers, method="GET")
            with urlopen(request, timeout=8) as response:
                if response.status >= 400:
                    return ConnectionTestResult(False, f"供应商返回 HTTP {response.status}。")
            latency = max(1, round((monotonic() - started) * 1000))
            return ConnectionTestResult(True, f"已连接 {config.provider}，模型目录接口响应正常。", latency)
        except HTTPError as exc:
            return ConnectionTestResult(False, f"供应商返回 HTTP {exc.code}，请检查地址或凭据。")
        except (URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", None) or "网络不可达"
            return ConnectionTestResult(False, f"连接失败：{reason}")


class UnavailableConnectionTester(ProviderConnectionTester):
    """Backward-compatible name for integrations that imported the old adapter."""
