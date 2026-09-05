"""Celery entry points for asynchronous agent graph execution."""
from typing import Any
from celery import shared_task
from apps.agents.graph import build_agent_graph


@shared_task(bind=True, name="agents.run_graph")
def run_agent_graph(self, state: dict[str, Any]) -> dict[str, Any]:
    """Execute a serialized AgentState and return a serialized final state."""
    try:
        return build_agent_graph().invoke(state)
    except Exception as exc:
        return {**state, "execution_status": "failed", "error_message": str(exc)}
