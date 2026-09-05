"""Typed state contract shared by future LangGraph agent nodes."""
from typing import Any, Literal, TypedDict
from uuid import uuid4

ExecutionStatus = Literal["pending", "running", "paused", "completed", "failed", "cancelled"]
InterruptSignal = Literal["", "pause", "stop", "cancel"]


class Message(TypedDict):
    """Normalized conversation message."""
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class AgentState(TypedDict, total=False):
    """Serializable state passed between agent orchestration nodes."""
    messages: list[Message]
    user_input: str
    conversation_id: str
    project_id: str
    user_id: str
    selected_environment: str | None
    intent: str
    entities: dict[str, Any]
    clarified_questions: list[str]
    requirement_document_id: str | None
    requirement_analysis: dict[str, Any]
    case_generation: dict[str, Any]
    knowledge_context: list[dict[str, Any]]
    plan: dict[str, Any]
    selected_skills: list[str]
    execution_order: list[str]
    execution_results: list[dict[str, Any]]
    execution_status: ExecutionStatus
    route: str
    interrupt_signal: InterruptSignal
    analysis: dict[str, Any]
    needs_replan: bool
    should_learn: bool
    should_report: bool
    should_notify: bool
    final_report: dict[str, Any]
    error_message: str


def new_agent_state(user_input: str, project_id: str, user_id: str, conversation_id: str | None = None) -> AgentState:
    """Create a safe initial state for a new conversation."""
    if not user_input.strip() or not project_id.strip() or not user_id.strip():
        raise ValueError("AgentState requires non-empty user_input, project_id and user_id。")
    return {"messages": [{"role": "user", "content": user_input}], "user_input": user_input, "conversation_id": conversation_id or str(uuid4()), "project_id": project_id, "user_id": user_id, "selected_environment": None, "intent": "", "entities": {}, "clarified_questions": [], "requirement_document_id": None, "requirement_analysis": {}, "case_generation": {}, "knowledge_context": [], "plan": {}, "selected_skills": [], "execution_order": [], "execution_results": [], "execution_status": "pending", "route": "", "interrupt_signal": "", "analysis": {}, "needs_replan": False, "should_learn": False, "should_report": False, "should_notify": False, "final_report": {}, "error_message": ""}


def validate_agent_state(state: AgentState) -> None:
    """Validate identity, message shape, lifecycle and interruption fields."""
    required = ("user_input", "conversation_id", "project_id", "user_id")
    if any(not isinstance(state.get(field), str) or not state[field].strip() for field in required):
        raise ValueError("AgentState 身份和输入字段不能为空。")
    if state.get("execution_status") not in {"pending", "running", "paused", "completed", "failed", "cancelled"}:
        raise ValueError("AgentState execution_status 无效。")
    if state.get("interrupt_signal", "") not in {"", "pause", "stop", "cancel"}:
        raise ValueError("AgentState interrupt_signal 无效。")
    for message in state.get("messages", []):
        if message.get("role") not in {"system", "user", "assistant", "tool"} or not isinstance(message.get("content"), str):
            raise ValueError("AgentState messages 格式无效。")
