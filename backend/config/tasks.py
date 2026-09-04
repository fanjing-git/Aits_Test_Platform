"""Small infrastructure tasks used for service health verification."""

from celery import shared_task


@shared_task(name="config.health_probe")
def health_probe() -> dict[str, str]:
    """Return a deterministic payload for Celery integration checks."""
    return {"status": "ok", "component": "celery"}

