"""Decision and routing contract for the future agent graph."""
from typing import Any
from apps.agents.state import AgentState

INTENT_ROUTES = {"requirement_analysis": "requirement_analysis", "case_gen": "case_generation", "api_test": "api_test", "ai_test": "ai_test", "ui_test": "ui_test", "app_test": "app_test", "perf_test": "perf_test", "security_test": "security_test", "knowledge_search": "reflect", "environment_check": "reflect", "other": "reflect"}


def decide_node(state: AgentState) -> AgentState:
    """Choose the next graph node while honoring interruption signals."""
    intent = state.get("intent", "")
    if not intent:
        raise ValueError("决策节点需要先完成意图识别。")
    signal = state.get("interrupt_signal", "")
    if signal not in {"", "pause", "stop", "cancel"}:
        raise ValueError("决策节点收到无效打断信号。")
    route = "wait_for_input" if signal == "pause" else "cancelled" if signal in {"stop", "cancel"} else INTENT_ROUTES.get(intent, "reflect")
    result = dict(state)
    result["route"] = route
    result["execution_status"] = "paused" if signal == "pause" else "cancelled" if signal in {"stop", "cancel"} else "pending"
    result["plan"] = {**state.get("plan", {}), "route": route}
    return result


def route_for_intent(intent: str) -> str:
    """Return a stable route for an intent, using reflect as safe fallback."""
    return INTENT_ROUTES.get(intent, "reflect")
