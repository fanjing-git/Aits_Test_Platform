"""Requirement analysis, case generation and review nodes."""
from typing import Any
from apps.agents.state import AgentState


def requirement_analysis_node(state: AgentState) -> AgentState:
    """Convert the current requirement into an auditable analysis structure."""
    text = state.get("user_input", "").strip()
    if not text:
        raise ValueError("需求分析需要 user_input。")
    analysis = {"summary": text, "actors": [], "acceptance_points": [text], "risks": [], "source_document_id": state.get("requirement_document_id")}
    result = dict(state); result["requirement_analysis"] = analysis; return result


def case_generation_node(state: AgentState) -> AgentState:
    """Generate positive, negative and boundary case drafts from analysis."""
    analysis = state.get("requirement_analysis", {})
    summary = str(analysis.get("summary", "")).strip()
    if not summary:
        raise ValueError("用例生成需要先完成需求分析。")
    cases = [{"id": "case-1", "type": "positive", "title": f"{summary} - 正常流程", "status": "draft"}, {"id": "case-2", "type": "negative", "title": f"{summary} - 异常输入", "status": "draft"}, {"id": "case-3", "type": "boundary", "title": f"{summary} - 边界条件", "status": "draft"}]
    result = dict(state); result["case_generation"] = {"cases": cases, "count": len(cases), "status": "draft"}; return result


def case_review_node(state: AgentState) -> AgentState:
    """Review generated drafts for required categories and mark them reviewed."""
    generation = state.get("case_generation", {})
    cases = generation.get("cases", [])
    if not isinstance(cases, list) or not cases:
        raise ValueError("用例评审需要先生成用例。")
    required = {"positive", "negative", "boundary"}; actual = {item.get("type") for item in cases if isinstance(item, dict)}
    result = dict(state); result["case_generation"] = {**generation, "review": {"approved": required.issubset(actual), "missing_types": sorted(required - actual), "reviewed_count": len(cases)}, "status": "reviewed"}; return result
