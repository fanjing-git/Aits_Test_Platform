"""Reflection, learning and reporting nodes for agent orchestration."""
from datetime import datetime, timezone
from typing import Any
from apps.agents.state import AgentState


def reflect_node(state: AgentState) -> AgentState:
    """Summarize execution outcomes and decide whether replanning is needed."""
    results = state.get("execution_results", [])
    failures = [item for item in results if isinstance(item, dict) and item.get("status") in {"failed", "error"}]
    result = dict(state)
    result["analysis"] = {"result_count": len(results), "failure_count": len(failures), "summary": "存在失败结果，需要重新规划。" if failures else "执行结果正常，可生成报告。"}
    result["needs_replan"] = bool(failures)
    result["should_learn"] = bool(results)
    result["should_report"] = True
    return result


def learn_node(state: AgentState) -> AgentState:
    """Prepare a reviewable learning candidate without persisting it."""
    analysis = state.get("analysis", {})
    result = dict(state)
    result["analysis"] = {**analysis, "learning_candidate": {"source": "agent_execution", "summary": analysis.get("summary", ""), "requires_review": True}}
    return result


def report_node(state: AgentState) -> AgentState:
    """Generate a stable final report from current state without exposing secrets."""
    result = dict(state)
    result["final_report"] = {"conversation_id": state.get("conversation_id", ""), "project_id": state.get("project_id", ""), "intent": state.get("intent", "other"), "status": state.get("execution_status", "pending"), "analysis": state.get("analysis", {}), "selected_skills": state.get("selected_skills", []), "knowledge_count": len(state.get("knowledge_context", [])), "generated_at": datetime.now(timezone.utc).isoformat()}
    return result
