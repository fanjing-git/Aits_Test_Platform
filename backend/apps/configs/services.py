"""Provider-specific discovery and explicit, bounded connection probes."""

import json
import ipaddress
import re
import socket
import ssl
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from time import monotonic
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from apps.configs.catalog import (
    MANUAL_ONLY_PROVIDERS,
    OFFICIAL_DIRECTORY_PROVIDERS,
    PROVIDER_TYPES,
    PROVIDERS,
    normalize_model,
)
from apps.configs.models import ModelConfig
from core.utils.crypto import SecretDecryptionError


class ProviderError(ValueError):
    """A sanitized, actionable upstream failure safe for API responses."""

    def __init__(self, message: str, code: str = "provider_error") -> None:
        super().__init__(message)
        self.code = code


PROVIDER_HOST_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "openai": ("api.openai.com",),
    "anthropic": ("api.anthropic.com",),
    "google": ("generativelanguage.googleapis.com",),
    "qwen": ("dashscope.aliyuncs.com", ".dashscope.aliyuncs.com", ".maas.aliyuncs.com"),
    "baidu": ("qianfan.baidubce.com",),
    "deepseek": ("api.deepseek.com",),
    "zhipu": ("open.bigmodel.cn",),
    "azure": (".openai.azure.com", ".cognitiveservices.azure.com"),
}
ALLOWED_PROVIDER_PORTS = {"https": frozenset({443}), "http": frozenset({80})}
LOCAL_PROVIDER_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
BLOCKED_PROVIDER_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("100.64.0.0/10", "169.254.0.0/16", "fe80::/10")
)
BLOCKED_PROVIDER_IPS = frozenset({"169.254.169.254", "100.100.100.200", "fd00:ec2::254"})


class NoRedirect(HTTPRedirectHandler):
    """Never forward credentials to a redirect destination."""

    def redirect_request(self, req: Request, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


def _host_matches(host: str, patterns: tuple[str, ...]) -> bool:
    """Return whether a hostname is an exact or explicit subdomain match."""
    normalized = host.rstrip(".").lower()
    return any(
        normalized == pattern or (pattern.startswith(".") and normalized.endswith(pattern))
        for pattern in patterns
    )


def _is_blocked_provider_ip(value: str) -> bool:
    """Reject address classes that must never be contacted by a provider probe."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return True
    if str(address) in BLOCKED_PROVIDER_IPS:
        return True
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
        or address.is_multicast
    ):
        return True
    return any(address in network for network in BLOCKED_PROVIDER_NETWORKS)


def _resolve_provider_host(host: str, port: int) -> None:
    """Resolve a provider host immediately before opening a request and reject unsafe IPs."""
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ProviderError("无法解析供应商地址，请检查 DNS 和服务器网络。", "dns_failed") from exc
    if not addresses:
        raise ProviderError("供应商地址没有可用的 DNS 记录。", "dns_failed")
    for address in {item[4][0] for item in addresses}:
        if _is_blocked_provider_ip(address):
            raise ProviderError("供应商地址解析到受禁止的内网或保留地址。", "unsafe_target")


def validate_outbound_endpoint(provider: str, endpoint: str) -> None:
    """Validate provider destinations before any socket or proxy request is opened."""
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").rstrip(".").lower()
    if parts.scheme not in {"http", "https"} or not host:
        raise ProviderError("请填写有效的 HTTP(S) API 基础地址。", "invalid_url")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise ProviderError("API 地址端口无效。", "invalid_url") from exc
    if provider == "local":
        if host not in LOCAL_PROVIDER_HOSTS:
            raise ProviderError("本地模型只能连接本机地址。", "unsafe_target")
        return
    if parts.scheme != "https":
        raise ProviderError("外部模型供应商必须使用 HTTPS 地址。", "unsafe_target")
    if port not in ALLOWED_PROVIDER_PORTS[parts.scheme]:
        raise ProviderError("外部模型供应商只允许使用 HTTPS 443 端口。", "unsafe_target")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ProviderError("外部模型地址必须使用受信域名，不能直接填写 IP。", "unsafe_target")
    patterns = PROVIDER_HOST_ALLOWLIST.get(provider)
    if patterns and not _host_matches(host, patterns):
        raise ProviderError("该供应商地址不在允许的域名范围内。", "unsafe_target")
    _resolve_provider_host(host, port)


def urlopen(request: Request, timeout: float = 8, *, provider: str = "") -> Any:
    """Open one validated request with redirects disabled and normal TLS verification."""
    validate_outbound_endpoint(provider, request.full_url)
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


def request_json(
    config: ModelConfig,
    endpoint: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 8,
) -> dict[str, Any]:
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
        with urlopen(request, timeout=timeout, provider=config.provider) as response:
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
        code = "provider_http_error"
        if exc.code in {401, 403}:
            code = "auth_failed"
        elif exc.code in {402, 429}:
            code = "quota_exhausted"
        elif exc.code == 407:
            code = "proxy_unavailable"
        message = messages.get(exc.code, "供应商服务异常，请稍后重试。")
        if 300 <= exc.code < 400:
            message = "API 地址发生重定向，为保护密钥已停止，请填写最终地址。"
        raise ProviderError(f"HTTP {exc.code}：{message}", code) from exc
    except (URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        winerror = getattr(exc, "winerror", None) or getattr(reason, "winerror", None)
        if winerror == 10013 or "10013" in str(exc):
            raise ProviderError(
                '本机网络策略拒绝了 Django/Python 的外网连接（WinError 10013），请放行后端进程或配置代理。',
                'local_network_blocked',
            ) from exc
        if "proxy" in str(exc).lower() or "407" in str(exc):
            raise ProviderError("代理服务器不可用或拒绝了请求，请检查代理地址、认证和 CA 证书。", "proxy_unavailable") from exc
        if isinstance(reason, socket.gaierror):
            raise ProviderError("无法解析供应商地址，请检查 DNS 和服务器网络。", "dns_failed") from exc
        if isinstance(reason, ssl.SSLError):
            raise ProviderError("与供应商建立 TLS 连接失败，请检查证书、系统时间和代理 CA。", "tls_failed") from exc
        if isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            raise ProviderError("模型供应商响应超时，请稍后重试或调整模型超时配置。", "provider_timeout") from exc
        raise ProviderError("无法建立供应商网络连接，请检查 TCP 出站策略、代理和 API 地址。", "tcp_blocked") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProviderError("供应商没有返回有效 JSON，可能填写了网页地址。", "invalid_response") from exc


OPENAI_COMPATIBLE_PROVIDERS = frozenset({"openai", "qwen", "deepseek", "azure", "custom", "local"})
DEFAULT_STRUCTURED_TIMEOUT_SECONDS = 120
MAX_STRUCTURED_TIMEOUT_SECONDS = 120


def structured_timeout(config: ModelConfig) -> int:
    """Return a bounded structured-call timeout from model parameters."""
    parameters = config.parameters if isinstance(config.parameters, dict) else {}
    raw_value = parameters.get("structured_timeout_seconds", DEFAULT_STRUCTURED_TIMEOUT_SECONDS)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = DEFAULT_STRUCTURED_TIMEOUT_SECONDS
    return max(1, min(MAX_STRUCTURED_TIMEOUT_SECONDS, value))


def openai_compatible_payload(
    config: ModelConfig,
    *,
    messages: Sequence[Mapping[str, Any]],
    max_tokens: int,
    temperature: float = 0,
    structured: bool = True,
) -> dict[str, Any]:
    """Build one consistent OpenAI-compatible chat payload for probes and business calls."""
    parameters = config.parameters if isinstance(config.parameters, dict) else {}
    payload: dict[str, Any] = {
        "model": config.model_name,
        "messages": [dict(message) for message in messages],
        "temperature": temperature,
        "stream": False,
    }
    token_limit = max(1, int(max_tokens))
    token_field = "max_completion_tokens" if config.provider in {"openai", "azure"} else "max_tokens"
    payload[token_field] = token_limit
    if structured:
        payload["response_format"] = {"type": "json_object"}
    if config.provider == "qwen":
        payload["enable_thinking"] = bool(parameters.get("enable_thinking", False))
    elif config.provider == "deepseek":
        thinking = parameters.get("thinking", {"type": "disabled"})
        if isinstance(thinking, str):
            thinking = {"type": thinking}
        if isinstance(thinking, Mapping):
            payload["thinking"] = dict(thinking)
    return payload


def openai_compatible_chat(
    config: ModelConfig,
    *,
    messages: Sequence[Mapping[str, Any]],
    max_tokens: int,
    temperature: float = 0,
    structured: bool = True,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Send a bounded OpenAI-compatible chat request through the shared transport."""
    if config.provider not in OPENAI_COMPATIBLE_PROVIDERS:
        raise ProviderError("当前供应商不属于 OpenAI-compatible 协议范围。", "protocol_not_supported")
    base = canonical_base(config.provider, config.api_base_url)
    payload = openai_compatible_payload(
        config,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        structured=structured,
    )
    return request_json(
        config,
        f"{base}/chat/completions",
        payload,
        timeout=structured_timeout(config) if timeout is None else timeout,
    )


def extract_openai_message_content(response: Mapping[str, Any]) -> str:
    """Extract text content from a standard or multipart OpenAI-compatible response."""
    try:
        message = response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("供应商响应缺少 choices.message 结构。", "invalid_response") from exc
    content = message.get("content") if isinstance(message, Mapping) else None
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [item.get("text", "") for item in content if isinstance(item, Mapping)]
        normalized = "".join(part for part in parts if isinstance(part, str)).strip()
        if normalized:
            return normalized
    raise ProviderError("供应商响应没有可解析的模型内容。", "invalid_response")


def parse_openai_json_response(response: Mapping[str, Any]) -> dict[str, Any]:
    """Parse a JSON object returned in an OpenAI-compatible message content field."""
    choices = response.get("choices") if isinstance(response, Mapping) else None
    first_choice = choices[0] if isinstance(choices, list) and choices else None
    finish_reason = first_choice.get("finish_reason") if isinstance(first_choice, Mapping) else None
    if finish_reason in {"length", "max_tokens"}:
        raise ProviderError("模型输出达到长度上限，JSON 结果被截断；请提高结构化输出上限后重试。", "output_truncated")
    content = extract_openai_message_content(response)
    normalized = re.sub(
        r"<think>.*?</think>",
        "",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()
    normalized = re.sub(r"```(?:json)?", "", normalized, flags=re.IGNORECASE).replace("```", "").strip()
    try:
        result = json.loads(normalized)
    except (TypeError, json.JSONDecodeError) as exc:
        # Some compatible endpoints add a short preamble or suffix even when
        # response_format=json_object is requested. Decode only the first JSON
        # object and leave strict business-schema validation to the caller.
        start = normalized.find("{")
        if start >= 0:
            try:
                result, _ = json.JSONDecoder().raw_decode(normalized[start:])
            except json.JSONDecodeError:
                result = None
        else:
            result = None
        if result is None:
            raise ProviderError("供应商返回内容不是有效 JSON。", "invalid_response") from exc
    if not isinstance(result, dict):
        raise ProviderError("供应商返回的 JSON 不是对象。", "invalid_response")
    return result


def _anthropic_content(content: Any) -> str | list[dict[str, Any]]:
    """Convert text or OpenAI-style image content to Anthropic blocks."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise ProviderError("Anthropic 消息内容格式不受支持。", "unsupported_content")
    blocks: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, Mapping):
            continue
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            blocks.append({"type": "text", "text": item["text"]})
            continue
        image_url = item.get("image_url")
        url = image_url.get("url") if isinstance(image_url, Mapping) else None
        match = re.fullmatch(r"data:([^;]+);base64,(.+)", url or "")
        if item.get("type") == "image_url" and match:
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": match.group(1), "data": match.group(2)},
            })
            continue
        raise ProviderError("Anthropic 当前仅支持文本和内嵌图片输入。", "unsupported_content")
    return blocks


def _google_content(content: Any) -> list[dict[str, Any]]:
    """Convert text or OpenAI-style image content to Gemini parts."""
    if isinstance(content, str):
        return [{"text": content}]
    if not isinstance(content, list):
        raise ProviderError("Google Gemini 消息内容格式不受支持。", "unsupported_content")
    parts: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, Mapping):
            continue
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append({"text": item["text"]})
            continue
        image_url = item.get("image_url")
        url = image_url.get("url") if isinstance(image_url, Mapping) else None
        match = re.fullmatch(r"data:([^;]+);base64,(.+)", url or "")
        if item.get("type") == "image_url" and match:
            parts.append({"inlineData": {"mimeType": match.group(1), "data": match.group(2)}})
            continue
        raise ProviderError("Google Gemini 当前仅支持文本和内嵌图片输入。", "unsupported_content")
    return parts


def _native_message_response(provider: str, response: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize native provider text responses to the shared JSON parser shape."""
    finish_reason = None
    if provider == "anthropic":
        content = response.get("content")
        parts = [item.get("text", "") for item in content or [] if isinstance(item, Mapping)]
        text = "".join(part for part in parts if isinstance(part, str)).strip()
        finish_reason = response.get("stop_reason")
    elif provider == "google":
        candidates = response.get("candidates")
        parts = ((candidates or [{}])[0].get("content") or {}).get("parts", []) if isinstance(candidates, list) else []
        text = "".join(item.get("text", "") for item in parts if isinstance(item, Mapping)).strip()
        finish_reason = (candidates or [{}])[0].get("finishReason") if isinstance(candidates, list) and candidates else None
    else:
        return dict(response)
    if not text:
        raise ProviderError("供应商响应没有可解析的模型内容。", "invalid_response")
    normalized_reason = "length" if str(finish_reason).casefold() in {"length", "max_tokens", "max_tokens_reached"} else finish_reason
    choice = {"message": {"content": text}}
    if normalized_reason:
        choice["finish_reason"] = normalized_reason
    return {"choices": [choice]}


def native_structured_chat(
    config: ModelConfig,
    *,
    messages: Sequence[Mapping[str, Any]],
    max_tokens: int,
    temperature: float = 0,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Call a native non-OpenAI protocol and normalize its response."""
    if config.provider == "anthropic":
        system_parts: list[str] = []
        native_messages: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role", "user"))
            content = message.get("content", "")
            if role == "system":
                if isinstance(content, str):
                    system_parts.append(content)
                continue
            native_messages.append({"role": "assistant" if role == "assistant" else "user", "content": _anthropic_content(content)})
        payload: dict[str, Any] = {
            "model": config.model_name,
            "max_tokens": max(1, int(max_tokens)),
            "messages": native_messages,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        response = request_json(config, f"{canonical_base(config.provider, config.api_base_url)}/messages", payload, timeout=timeout or structured_timeout(config))
        return _native_message_response(config.provider, response)
    if config.provider == "google":
        contents: list[dict[str, Any]] = []
        system_instruction: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role", "user"))
            parts = _google_content(message.get("content", ""))
            if role == "system":
                system_instruction.extend(parts)
            else:
                contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
        generation_config: dict[str, Any] = {"maxOutputTokens": max(1, int(max_tokens)), "temperature": temperature}
        generation_config["responseMimeType"] = "application/json"
        payload = {"contents": contents, "generationConfig": generation_config}
        if system_instruction:
            payload["systemInstruction"] = {"parts": system_instruction}
        endpoint = f"{canonical_base(config.provider, config.api_base_url)}/models/{quote(config.model_name, safe='')}:generateContent"
        response = request_json(config, endpoint, payload, timeout=timeout or structured_timeout(config))
        return _native_message_response(config.provider, response)
    if config.provider in {"baidu", "zhipu"}:
        temperature_value = max(0.1, temperature) if config.provider == "zhipu" else temperature
        payload = {
            "model": config.model_name,
            "messages": [dict(message) for message in messages],
            "temperature": temperature_value,
            "max_tokens": max(1, int(max_tokens)),
            "stream": False,
        }
        response = request_json(
            config,
            f"{canonical_base(config.provider, config.api_base_url)}/chat/completions",
            payload,
            timeout=timeout or structured_timeout(config),
        )
        if not isinstance(response.get("choices"), list) or not response["choices"]:
            raise ProviderError("供应商响应缺少 choices 结构。", "invalid_response")
        return response
    raise ProviderError("当前供应商协议尚未适配结构化调用。", "protocol_not_supported")


def structured_chat(
    config: ModelConfig,
    *,
    messages: Sequence[Mapping[str, Any]],
    max_tokens: int,
    temperature: float = 0,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Dispatch one structured call to its declared provider protocol."""
    if config.provider in OPENAI_COMPATIBLE_PROVIDERS:
        return openai_compatible_chat(
            config,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            structured=True,
            timeout=timeout,
        )
    return native_structured_chat(
        config,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    )


def discover_models(config: ModelConfig, cursor: str = "") -> dict[str, Any]:
    """Read one provider page; clients follow the explicit next cursor."""
    if config.provider in MANUAL_ONLY_PROVIDERS:
        return {
            "models": [], "next_cursor": "", "total": 0,
            "source": "manual", "source_kind": "manual_only",
            "source_url": PROVIDERS.get(config.provider, ("", "", ""))[2],
            "source_version": None, "updated_at": None,
            "directory_state": "manual_only",
            "account_access_state": "not_checked",
            "model_call_state": "not_checked",
            "is_stale": False,
            "official_directory_supported": False,
            "manual_model_id_allowed": True,
            "complete": True,
            "message": "该 Provider 没有可靠的官方模型目录 API，请手工填写模型 ID 或部署名称。",
        }
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
            "source": "provider", "source_kind": "provider_directory",
            "source_url": PROVIDERS.get(protocol, ("", "", ""))[2],
            "source_version": "live-provider-directory",
            "updated_at": date.today().isoformat(),
            "directory_state": "available",
            "account_access_state": "catalog_accessible",
            "model_call_state": "not_checked",
            "is_stale": False,
            "official_directory_supported": protocol in OFFICIAL_DIRECTORY_PROVIDERS,
            "manual_model_id_allowed": True,
            "complete": not bool(next_cursor),
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
    directory_state: str = "not_checked"
    account_access_state: str = "not_checked"
    model_state: str = "not_checked"
    model_call_state: str = "not_checked"
    source_kind: str = ""


class ConnectionTester(Protocol):
    """Boundary for injectable non-billable test doubles."""

    def test(self, config: ModelConfig) -> ConnectionTestResult: ...


def inference_probe(config: ModelConfig) -> None:
    """Make one minimal explicit invocation, never retry billable POSTs."""
    kind, model = config.model_type, config.model_name
    base = canonical_base(config.provider, config.api_base_url)
    supported_types = PROVIDER_TYPES.get(config.provider)
    if supported_types and kind not in supported_types:
        raise ProviderError("该供应商当前未声明支持所选模型能力。", "capability_not_supported")
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
        base = canonical_base(config.provider, config.api_base_url)
        endpoint = f"{base}/embeddings"
        payload = {"model": model, "input": "ping"}
    elif config.provider in OPENAI_COMPATIBLE_PROVIDERS:
        result = openai_compatible_chat(
            config,
            messages=(
                {"role": "system", "content": "Return a JSON object only."},
                {"role": "user", "content": "Reply with {\"ok\":true}."},
            ),
            max_tokens=16,
            structured=True,
        )
        parsed = parse_openai_json_response(result)
        if parsed.get("ok") is not True:
            raise ProviderError("响应未包含有效 JSON 探测结果，不能判定调用成功。", "invalid_response")
        return
    elif config.provider in {"baidu", "zhipu"}:
        result = native_structured_chat(
            config,
            messages=({"role": "user", "content": "Reply OK."},),
            max_tokens=16,
        )
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderError("响应未包含有效模型结果，不能判定调用成功。", "invalid_response")
        return
    else:
        base = canonical_base(config.provider, config.api_base_url)
        endpoint = f"{base}/chat/completions"
        payload = {"model": model, "messages": [{"role": "user", "content": "Reply OK."}], "stream": False}
        payload["max_completion_tokens" if config.provider in {"openai", "azure"} else "max_tokens"] = 16
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
        catalog_meta: dict[str, Any] = {}
        try:
            if mode == "inference":
                inference_probe(config)
                detail = "（文本探测，未验证图片理解）" if config.model_type == "vision" else ""
                return ConnectionTestResult(
                    True, f"所选模型实际调用成功{detail}。",
                    max(1, round((monotonic() - started) * 1000)), "inference", True,
                    directory_state="not_checked", account_access_state="verified",
                    model_state="callable", model_call_state="callable",
                    source_kind="inference_probe",
                )
            cursor = ""
            seen = set()
            for _ in range(100):
                page = discover_models(config, cursor)
                catalog_meta = page
                if page.get("directory_state") == "manual_only":
                    return ConnectionTestResult(
                        False, page["message"], max(1, round((monotonic() - started) * 1000)),
                        code="manual_model_required", directory_state="manual_only",
                        account_access_state="not_checked", model_state="manual_required",
                        model_call_state="not_checked", source_kind="manual_only",
                    )
                if any(item["id"] == config.model_name for item in page["models"]):
                    return ConnectionTestResult(
                        True, f"已连接 {config.provider}，目录中存在所选模型；尚未验证实际调用。",
                        max(1, round((monotonic() - started) * 1000)),
                        directory_state="available", account_access_state="catalog_accessible",
                        model_state="listed", model_call_state="not_checked",
                        source_kind="provider_directory",
                    )
                cursor = page["next_cursor"]
                if not cursor:
                    raise ProviderError("服务目录连接成功，但未找到所选模型；请同步目录或使用部署名称进行实际调用测试。", "model_not_listed")
                if cursor in seen or monotonic() - started > 20:
                    raise ProviderError("目录分页未完成，请先同步模型列表后重试。", "catalog_incomplete")
                seen.add(cursor)
            raise ProviderError("模型目录超过本次检查上限，请先同步目录。", "catalog_incomplete")
        except (ProviderError, ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            message = str(exc) if isinstance(exc, ProviderError) else "供应商响应格式异常，请检查协议与模型类型。"
            code = getattr(exc, "code", "invalid_response")
            directory_state = catalog_meta.get("directory_state", "unavailable")
            account_access_state = catalog_meta.get("account_access_state", "unknown")
            model_state = "not_listed" if code == "model_not_listed" else "unknown"
            if code == "auth_failed":
                account_access_state = "denied"
            return ConnectionTestResult(
                False, message, stage=mode, code=code,
                directory_state=directory_state,
                account_access_state=account_access_state,
                model_state=model_state,
                model_call_state="not_checked",
                source_kind=catalog_meta.get("source_kind", "provider_directory"),
            )


class UnavailableConnectionTester(ProviderConnectionTester):
    """Backward-compatible adapter import."""
