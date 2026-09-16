"""Resolve and check the explicitly configured user access entrypoint."""

from __future__ import annotations

from datetime import datetime, timezone
from ipaddress import ip_address
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings


class DeploymentAccessError(ValueError):
    """Raised when the configured public application URL is unsafe or missing."""


class _NoRedirectHandler(HTTPRedirectHandler):
    """Prevent an access check from following an untrusted redirect."""

    def redirect_request(self, *args: object, **kwargs: object):
        """Return no follow-up request so redirect targets cannot bypass checks."""
        return None


def normalize_access_url(value: str, name: str = "PUBLIC_APP_URL") -> str:
    """Validate and normalize one explicitly configured HTTP(S) origin."""
    raw = value.strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise DeploymentAccessError(f"{name} must be an absolute HTTP or HTTPS URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise DeploymentAccessError(f"{name} must not contain credentials, query parameters or fragments.")
    try:
        parsed.port
    except ValueError as exc:
        raise DeploymentAccessError(f"{name} contains an invalid port.") from exc
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def classify_access_scope(url: str) -> str:
    """Classify a configured URL without enumerating or resolving host interfaces."""
    hostname = urlsplit(url).hostname or ""
    if hostname.lower() == "localhost" or hostname.lower().endswith(".local"):
        return "private"
    try:
        address = ip_address(hostname)
    except ValueError:
        return "public"
    return "private" if address.is_private or address.is_loopback or address.is_link_local else "public"


class DeploymentAccessService:
    """Provide safe access metadata and an explicit no-redirect health probe."""

    @staticmethod
    def configured_app_url() -> str:
        """Return the normalized configured browser entrypoint or raise a safe error."""
        value = normalize_access_url(getattr(settings, "PUBLIC_APP_URL", ""))
        if not value:
            raise DeploymentAccessError("尚未配置规范用户访问地址，请设置 PUBLIC_APP_URL。")
        return value

    @classmethod
    def build_link(cls, path: str) -> str:
        """Build an invitation or password-action URL from the configured app origin."""
        if not path.startswith("/"):
            path = f"/{path}"
        return urljoin(f"{cls.configured_app_url()}/", path.lstrip("/"))

    @classmethod
    def describe(cls) -> dict[str, object]:
        """Return safe configured entrypoint metadata without probing the network."""
        app_url = normalize_access_url(getattr(settings, "PUBLIC_APP_URL", ""))
        api_url = normalize_access_url(getattr(settings, "PUBLIC_API_URL", ""), "PUBLIC_API_URL")
        if not app_url:
            return {
                "configured": False,
                "app_url": "",
                "api_url": api_url,
                "protocol": "",
                "port": None,
                "access_scope": "unknown",
                "access_scope_label": "未配置",
                "tls_status": "unknown",
                "tls_status_label": "未配置",
                "health_check_url": "",
                "health_status": "not_configured",
                "health_status_label": "未检查",
                "health_message": "请配置 PUBLIC_APP_URL 后再分享给同事。",
                "last_checked_at": None,
                "warning": "系统不会自动推断公网 IP、容器地址或后端端口。",
            }
        parsed = urlsplit(app_url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return {
            "configured": True,
            "app_url": app_url,
            "api_url": api_url,
            "protocol": parsed.scheme.upper(),
            "port": port,
            "access_scope": classify_access_scope(app_url),
            "access_scope_label": "公网/可分享" if classify_access_scope(app_url) == "public" else "内网或本机",
            "tls_status": "enabled" if parsed.scheme == "https" else "disabled",
            "tls_status_label": "HTTPS 已启用" if parsed.scheme == "https" else "HTTP 未启用 TLS",
            "health_check_url": urljoin(f"{api_url or app_url}/", "health/" if api_url else "api/health/"),
            "health_status": "unknown",
            "health_status_label": "尚未检查",
            "health_message": "点击检查入口和 API 可达性。",
            "last_checked_at": None,
            "warning": "仅显示显式配置的用户入口，不展示数据库、Redis、Docker 或 SSH 地址。",
        }

    @classmethod
    def check(cls) -> dict[str, object]:
        """Probe the configured health URL once without credentials or redirects."""
        result = cls.describe()
        if not result["configured"]:
            return result
        checked_at = datetime.now(timezone.utc).isoformat()
        health_url = str(result["health_check_url"])
        request = Request(health_url, headers={"User-Agent": "AITS-Access-Check/1.0"})
        opener = build_opener(_NoRedirectHandler())
        try:
            with opener.open(request, timeout=3) as response:
                code = int(response.status)
            healthy = 200 <= code < 300
            result.update(
                health_status="healthy" if healthy else "unhealthy",
                health_status_label="健康" if healthy else "服务异常",
                health_message="用户入口和 API 健康检查通过。" if healthy else f"健康检查返回 HTTP {code}。",
            )
        except HTTPError as exc:
            result.update(
                health_status="unhealthy",
                health_status_label="服务异常",
                health_message=f"健康检查返回 HTTP {exc.code}，请检查反向代理和 API 路径。",
            )
        except (URLError, TimeoutError, OSError) as exc:
            result.update(
                health_status="unreachable",
                health_status_label="无法访问",
                health_message=f"入口暂时无法访问，请检查端口、反向代理或网络策略。({exc.__class__.__name__})",
            )
        result["last_checked_at"] = checked_at
        return result
