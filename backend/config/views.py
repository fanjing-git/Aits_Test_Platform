"""Project-level diagnostic views."""

from django.http import HttpRequest, JsonResponse


def health(request: HttpRequest) -> JsonResponse:
    """Return a minimal response proving that the Django service is available."""
    return JsonResponse({"status": "ok", "service": "ai-agent-test-platform"})

