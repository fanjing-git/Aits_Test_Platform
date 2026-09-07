"""Provider-specific discovery and explicit, bounded connection probes."""

import json
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from apps.configs.catalog import PROVIDERS, normalize_model
from apps.configs.models import ModelConfig
from core.utils.crypto import SecretDecryptionError


class ProviderError(ValueError):
    """A sanitized, actionable upstream failure safe for API responses."""

    def __init__(self, message: str, code: str = "provider_error") -> None:
        super().__init__(message)
        self.code = code


class NoRedirect(HTTPRedirectHandler):
    """Never forward credentials to a redirect destination."""

    def redirect_request(self, req: Request, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


def urlopen(request: Request, timeout: float = 8) -> Any:
    """Open one request with redirects disabled and normal TLS verification."""
    return build_opener(NoRedirect()).open(request, timeout=timeout)


def canonical_base(provider: str, supplied: str) -> str:
    """Normalize an address without guessing a different credential host."""
    base = (supplied or PROVIDERS[provider][1]).strip().rstrip("/")
    parts = urlsplit(base)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ProviderError("请填写有效的 HTTP(S) API 基础地址。", "invalid_url")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ProviderError("API 地址不能包含账号、密钥、查询参数或片段；请填写基础地址。", "invalid_url")
    try:
        parts.port
    except ValueError as exc:
        raise ProviderError("API 地址端口无效。", "invalid_url") from exc
    path = parts.path.rstrip("/")
    for suffix in ("/chat/completions", "/embeddings", "/messages", "/models"):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
            break
    if provider == "azure" and path in {"", "/openai"}:
        path = "/openai/v1"
    if provider == "local" and path in {"", "/api"}:
        path = "/v1"
    return urlunsplit((parts.scheme.lower(), parts.netloc, path, "", ""))


def credential(config: ModelConfig) -> str:
    """Read a key only in the request boundary; sanitize decryption failures."""
    try:
        key = config.get_api_key().strip()
    except SecretDecryptionError as exc:
        raise ProviderError("无法解密已保存密钥，请重新填写 API Key。", "key_decryption") from exc
    if not key and config.provider not in {"local", "custom"}:
        raise ProviderError("请填写该供应商的 API Key 后同步或测试。", "missing_key")
    if any(ord(char) < 32 or ord(char) > 126 for char in key):
        raise ProviderError("API Key 含无效字符，请检查是否误粘贴。", "invalid_key")
    return key


def request_json(config: ModelConfig, endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Use provider authentication, bounded reads and sanitized upstream errors."""
    key = credential(config)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if config.provider == "anthropic":
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    elif config.provider == "google":
        headers["x-goog-api-key"] = key
    elif config.provider == "azure":
        headers["api-key"] = key
    elif key:
        headers["Authorization"] = f"Bearer {key}"
    request = Request(endpoint, headers=headers, method="POST" if payload is not None else "GET",
                      data=json.dumps(payload).encode("utf-8") if payload is not None else None)
    try:
        with urlopen(request, timeout=8) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ProviderError("供应商响应过大，请缩小查询范围。", "response_too_large")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ProviderError("供应商返回的 JSON 结构不正确。", "invalid_response")
        if result.get("error") or result.get("success") is False or result.get("code"):
            raise ProviderError("供应商返回业务错误，请检查账号权限、额度、地域和模型名称。", "upstream_error")
        return result
    except HTTPError as exc:
        messages = {
            400: "请求不被接受，请检查模型类型、名称及接入协议。",
            401: "鉴权失败，请检查 API Key 与地域、业务空间是否匹配。",
            402: "账户额度不足，请检查供应商计费状态。",
            403: "没有访问权限，请检查模型授权、业务空间及账号状态。",
            404: "接口或模型不存在；该供应商可能不支持此目录接口，可改用实际调用测试。",
            405: "供应商不支持此目录接口，可改用实际调用测试。",
            429: "请求限流或额度不足，请检查配额后重试。",
        }
        message = messages.get(exc.code, "供应商服务异常，请稍后重试。")
        if 300 <= exc.code < 400:
            message = "API 地址发生重定向，为保护密钥已停止，请填写最终地址。"
        raise ProviderError(f"HTTP {exc.code}：{message}", f"http_{exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        winerror = getattr(exc, 'winerror', None)
        if winerror == 10013 or '10013' in str(exc):
            raise ProviderError(
                '本机网络策略拒绝了 Django/Python 的外网连接（WinError 10013），请放行后端进程或配置代理。',
                'local_network_blocked',
            ) from exc
        raise ProviderError('网络连接失败或超时，请检查网络、代理、TLS 与 API 地址。', 'network_error') from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProviderError("供应商没有返回有效 JSON，可能填写了网页地址。", "invalid_response") from exc


def discover_models(config: ModelConfig, cursor: str = "") -> dict[str, Any]:
    """Read one provider page; clients follow the explicit next cursor."""
    base = canonical_base(config.provider, config.api_base_url)
    parts = urlsplit(base)
    protocol = config.provider
    params: dict[str, Any] = {}
    endpoint = f"{base}/models"
    if protocol == "qwen" and not parts.hostname.startswith("coding"):
        endpoint = urlunsplit((parts.scheme, parts.netloc, "/api/v1/models", "", ""))
        if cursor and (not cursor.isdigit() or not 1 <= int(cursor) <= 10000):
            raise ProviderError("模型目录分页参数无效。", "invalid_cursor")
        params = {"page_no": int(cursor or "1"), "page_size": 100, "language": "zh-CN"}
    elif protocol == "google":
        params = {"pageSize": 1000}
        if cursor:
            params["pageToken"] = cursor
    elif protocol == "anthropic":
        params = {"limit": 1000}
        if cursor:
            params["after_id"] = cursor
    elif cursor:
        params["after"] = cursor
    response = request_json(config, endpoint + ("?" + urlencode(params) if params else ""))
    next_cursor = ""
    if protocol == "qwen" and "output" in response:
        output = response["output"]
        if not isinstance(output, dict):
            raise ProviderError("模型目录结构无效。", "invalid_response")
        rows = output.get("models")
        total = output.get("total")
        page = params.get("page_no", 1)
        size = output.get("page_size", 100)
        if isinstance(total, int) and isinstance(size, int) and size > 0 and page * size < total:
            next_cursor = str(page + 1)
    else:
        rows = response.get("models") if protocol == "google" else response.get("data")
        if protocol == "google":
            next_cursor = response.get("nextPageToken") or ""
        elif response.get("has_more"):
            next_cursor = response.get("last_id") or (rows[-1].get("id") if rows else "")
            if not next_cursor:
                raise ProviderError("目录标记有下一页但缺少分页标识。", "invalid_response")
        total = None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ProviderError("供应商返回的模型目录结构不正确。", "invalid_response")
    if not isinstance(next_cursor, str) or len(next_cursor) > 2000 or next_cursor == cursor and next_cursor:
        raise ProviderError("供应商返回无效分页标识。", "invalid_response")
    if next_cursor and not rows:
        raise ProviderError("供应商返回空分页，目录尚未完整加载。", "invalid_response")
    try:
        models = [normalize_model(row, protocol) for row in rows]
    except ValueError as exc:
        raise ProviderError("模型目录包含无效条目。", "invalid_response") from exc
    return {"models": models, "next_cursor": next_cursor, "total": total,
            "source": "provider", "complete": not bool(next_cursor),
            "message": "目录反映供应商返回的模型；调用权限与额度以实际调用为准。"}


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    """Distinguish discovery, model visibility and an actual inference probe."""

    ok: bool
    message: str
    latency_ms: int | None = None
    stage: str = "catalog"
    inference_verified: bool = False
    code: str = ""


class ConnectionTester(Protocol):
    """Boundary for injectable non-billable test doubles."""

    def test(self, config: ModelConfig) -> ConnectionTestResult: ...


def inference_probe(config: ModelConfig) -> None:
    """Make one minimal explicit invocation, never retry billable POSTs."""
    base = canonical_base(config.provider, config.api_base_url)
    kind, model = config.model_type, config.model_name
    if kind not in {"chat", "vision", "embedding"}:
        raise ProviderError("该能力需要专用媒体输入；可执行目录连接测试，本次不自动创建音视频或图像生成任务。", "probe_not_supported")
    if config.provider == "google":
        method = "embedContent" if kind == "embedding" else "generateContent"
        endpoint = f"{base}/models/{quote(model, safe='')}:{method}"
        content = {"parts": [{"text": "ping"}]}
        payload = {"content": content} if kind == "embedding" else {"contents": [content], "generationConfig": {"maxOutputTokens": 16}}
    elif config.provider == "anthropic":
        if kind == "embedding":
            raise ProviderError("Anthropic Messages 不提供向量接口，请检查类型。", "probe_not_supported")
        endpoint = f"{base}/messages"
        payload = {"model": model, "max_tokens": 16, "messages": [{"role": "user", "content": "Reply OK."}]}
    elif kind == "embedding":
        endpoint = f"{base}/embeddings"
        payload = {"model": model, "input": "ping"}
    else:
        endpoint = f"{base}/chat/completions"
        payload = {"model": model, "messages": [{"role": "user", "content": "Reply OK."}], "stream": False}
        payload["max_completion_tokens" if config.provider in {"openai", "azure"} else "max_tokens"] = 16
        if config.provider == "qwen":
            payload["enable_thinking"] = False
        if config.provider == "deepseek":
            payload["thinking"] = {"type": "disabled"}
    result = request_json(config, endpoint, payload)
    if kind == "embedding":
        vector = result.get("embedding", {}).get("values") if config.provider == "google" else (result.get("data") or [{}])[0].get("embedding")
        valid = isinstance(vector, list) and bool(vector) and all(isinstance(value, (int, float)) for value in vector)
    elif config.provider == "google":
        valid = bool(result.get("candidates"))
    elif config.provider == "anthropic":
        valid = result.get("type") == "message" and isinstance(result.get("content"), list) and bool(result["content"])
    else:
        choices = result.get("choices")
        valid = isinstance(choices, list) and bool(choices) and isinstance(choices[0], dict) and isinstance(choices[0].get("message"), dict)
    if not valid:
        raise ProviderError("响应未包含有效模型结果，不能判定调用成功。", "invalid_response")


class ProviderConnectionTester:
    """Verify the selected model through discovery or explicit inference."""

    DEFAULT_BASE_URLS = {key: data[1] for key, data in PROVIDERS.items()}

    def test(self, config: ModelConfig, mode: str = "catalog") -> ConnectionTestResult:
        """Return safe diagnostics; catalogue success is never inference proof."""
        started = monotonic()
        try:
            if mode == "inference":
                inference_probe(config)
                detail = "（文本探测，未验证图片理解）" if config.model_type == "vision" else ""
                return ConnectionTestResult(True, f"所选模型实际调用成功{detail}。", max(1, round((monotonic() - started) * 1000)), "inference", True)
            cursor = ""
            seen = set()
            for _ in range(100):
                page = discover_models(config, cursor)
                if any(item["id"] == config.model_name for item in page["models"]):
                    return ConnectionTestResult(True, f"已连接 {config.provider}，目录中存在所选模型；尚未验证实际调用。", max(1, round((monotonic() - started) * 1000)))
                cursor = page["next_cursor"]
                if not cursor:
                    raise ProviderError("服务目录连接成功，但未找到所选模型；请同步目录或使用部署名称进行实际调用测试。", "model_not_listed")
                if cursor in seen or monotonic() - started > 20:
                    raise ProviderError("目录分页未完成，请先同步模型列表后重试。", "catalog_incomplete")
                seen.add(cursor)
            raise ProviderError("模型目录超过本次检查上限，请先同步目录。", "catalog_incomplete")
        except (ProviderError, ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            message = str(exc) if isinstance(exc, ProviderError) else "供应商响应格式异常，请检查协议与模型类型。"
            return ConnectionTestResult(False, message, stage=mode, code=getattr(exc, "code", "invalid_response"))


class UnavailableConnectionTester(ProviderConnectionTester):
    """Backward-compatible adapter import."""
