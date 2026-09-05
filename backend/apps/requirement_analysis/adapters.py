"""Safe online document adapters with a provider-neutral interface."""
import json
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class DocumentContent:
    """Normalized fetched document content and source metadata."""
    title: str
    content: str
    source_type: str
    source_url: str


class DocumentAdapter(Protocol):
    """Contract for online document providers."""
    def can_handle(self, url: str) -> bool: ...
    def fetch(self, url: str) -> DocumentContent: ...


class WebAdapter:
    """Fetch public HTTP(S) content with bounded size and timeout."""
    source_type = "online_link"
    hosts: tuple[str, ...] = ()
    def can_handle(self, url: str) -> bool:
        """Return whether this adapter owns the URL host."""
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and any(parsed.netloc.lower().endswith(host) for host in self.hosts)
    def fetch(self, url: str) -> DocumentContent:
        """Fetch and decode UTF-8 text without sending credentials."""
        if not self.can_handle(url): raise ValueError("该适配器不支持此链接。")
        request = Request(url, headers={"User-Agent": "AITS-Document-Adapter/1.0", "Accept": "text/plain,text/html,application/json"})
        with urlopen(request, timeout=10) as response:
            content_length = int(response.headers.get("Content-Length", "0") or 0)
            if content_length > 10 * 1024 * 1024: raise ValueError("在线文档超过10MB限制。")
            body = response.read(10 * 1024 * 1024 + 1)
        if len(body) > 10 * 1024 * 1024: raise ValueError("在线文档超过10MB限制。")
        text = body.decode("utf-8-sig", errors="strict").replace("\r\n", "\n").replace("\r", "\n")
        return DocumentContent(urlparse(url).path.rsplit("/", 1)[-1] or "在线文档", text, self.source_type, url)


class TencentDocsAdapter(WebAdapter):
    """Tencent Docs adapter."""
    hosts = ("docs.qq.com",)

class FeishuAdapter(WebAdapter):
    """Feishu document adapter."""
    hosts = ("feishu.cn", "larksuite.com")

class NotionAdapter(WebAdapter):
    """Notion public page adapter."""
    hosts = ("notion.so", "notion.site")

class YuqueAdapter(WebAdapter):
    """Yuque document adapter."""
    hosts = ("yuque.com",)

class SwaggerAdapter(WebAdapter):
    """Swagger/OpenAPI JSON adapter."""
    source_type = "online_link"
    def can_handle(self, url: str) -> bool:
        """Recognize common OpenAPI JSON paths and Swagger hosts."""
        path = urlparse(url).path.lower()
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and (path.endswith((".json", "/swagger.json", "/openapi.json")) or "swagger" in path or "openapi" in path)
    def fetch(self, url: str) -> DocumentContent:
        """Fetch JSON and normalize it as readable text."""
        result = super().fetch(url)
        try: content = json.dumps(json.loads(result.content), ensure_ascii=False, indent=2)
        except json.JSONDecodeError as exc: raise ValueError("Swagger/OpenAPI 内容不是有效 JSON。") from exc
        return DocumentContent(result.title, content, result.source_type, url)

class GenericWebAdapter(WebAdapter):
    """Fallback adapter for arbitrary public HTTP(S) pages."""
    def can_handle(self, url: str) -> bool:
        """Handle valid HTTP(S) URLs not claimed by specialized adapters."""
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


ADAPTERS = (TencentDocsAdapter(), FeishuAdapter(), NotionAdapter(), YuqueAdapter(), SwaggerAdapter(), GenericWebAdapter())


def adapter_for(url: str) -> DocumentAdapter:
    """Select the first specialized adapter or generic web fallback."""
    for adapter in ADAPTERS[:-1]:
        if adapter.can_handle(url): return adapter
    if ADAPTERS[-1].can_handle(url): return ADAPTERS[-1]
    raise ValueError("仅支持 HTTP/HTTPS 在线文档链接。")
