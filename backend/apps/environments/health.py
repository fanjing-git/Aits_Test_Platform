"""Bounded health probes against explicitly approved endpoint origins."""
from dataclasses import dataclass
from time import monotonic
from urllib.parse import urlsplit
import requests
from django.conf import settings
from django.db.models import Case, Q, Value, When
from django.utils import timezone
from rest_framework.exceptions import ValidationError, APIException
from apps.environments.models import Environment, validate_environment_url


class StaleHealthCheck(APIException):
    """Reject a result superseded by a configuration edit or newer probe."""
    status_code = 409
    default_detail = "环境配置或检查结果已更新，请刷新后重新检查。"


@dataclass(frozen=True)
class HealthResult:
    """Safe health outcome without response bodies or credentials."""
    ok: bool
    message: str
    latency_ms: int


def probe_endpoint(url: str) -> HealthResult:
    """Issue one unauthenticated GET without proxies or redirects."""
    validate_environment_url(url)
    parts = urlsplit(url)
    origin = (parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80))
    allowed = []
    for item in settings.ENVIRONMENT_HEALTH_ALLOWED_ORIGINS:
        parsed = urlsplit(item)
        allowed.append((parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)))
    if origin not in allowed:
        raise ValidationError({"health_check_url": "该目标尚未获准健康检查，请联系管理员配置允许的目标地址。"})
    started = monotonic()
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.get(url, timeout=(2, 3), allow_redirects=False, stream=True, headers={"Accept": "application/json"}) as response:
                ok = 200 <= response.status_code < 300
                message = "健康检查通过。" if ok else f"健康检查返回 HTTP {response.status_code}，请检查服务状态或地址。"
    except requests.Timeout:
        ok, message = False, "健康检查超时，请检查服务响应。"
    except requests.RequestException:
        ok, message = False, "健康检查连接失败，请检查网络、证书或服务状态。"
    return HealthResult(ok, message, max(1, round((monotonic() - started) * 1000)))


def check_environment(environment: Environment) -> Environment:
    """Probe outside a transaction and conditionally persist fresh results."""
    if not environment.health_check_url:
        raise ValidationError({"health_check_url": "请先编辑环境并填写健康检查地址。"})
    started_at = timezone.now()
    result = probe_endpoint(environment.health_check_url)
    changed = Environment.objects.filter(pk=environment.pk, updated_at=environment.updated_at).filter(
        Q(health_checked_at__isnull=True) | Q(health_checked_at__lt=started_at)
    ).update(
        health_status=Environment.HealthStatus.HEALTHY if result.ok else Environment.HealthStatus.UNHEALTHY,
        status=Case(When(status=Environment.Status.MAINTENANCE, then=Value(Environment.Status.MAINTENANCE)), default=Value(Environment.Status.AVAILABLE if result.ok else Environment.Status.UNAVAILABLE)),
        health_checked_at=started_at, health_message=result.message, health_latency_ms=result.latency_ms,
    )
    if not changed:
        raise StaleHealthCheck()
    environment.refresh_from_db()
    return environment
