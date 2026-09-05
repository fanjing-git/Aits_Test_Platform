"""Celery tasks for periodic environment health checks."""
from typing import Any
from celery import shared_task
from apps.environments.health import check_environment
from apps.environments.models import Environment


@shared_task(name="environments.check_all_health")
def check_all_environment_health() -> dict[str, Any]:
    """Check every configured environment and isolate individual failures."""
    checked = healthy = unhealthy = skipped = 0
    errors: list[dict[str, str]] = []
    for environment_id in Environment.objects.values_list("id", flat=True).iterator():
        try:
            environment = Environment.objects.get(pk=environment_id)
            if not environment.health_check_url:
                skipped += 1
                continue
            result = check_environment(environment)
            checked += 1
            if result.health_status == Environment.HealthStatus.HEALTHY:
                healthy += 1
            else:
                unhealthy += 1
        except Exception as exc:  # noqa: BLE001 - one bad target must not stop the sweep
            errors.append({"environment_id": str(environment_id), "message": "健康检查未完成。"})
    return {"checked": checked, "healthy": healthy, "unhealthy": unhealthy, "skipped": skipped, "errors": errors}
