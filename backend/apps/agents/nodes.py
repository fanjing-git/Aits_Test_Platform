"""Deterministic perception and understanding nodes for the agent graph."""
import re
from typing import Any

from apps.agents.state import AgentState, Message

INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("requirement_analysis", ("需求分析", "分析需求", "需求文档")),
    ("case_gen", ("用例生成", "测试用例", "生成用例")),
    ("api_test", ("接口测试", "api测试", "接口")),
    ("ai_test", ("ai测试", "模型评测", "大模型测试")),
    ("ui_test", ("ui测试", "页面测试", "浏览器测试")),
    ("app_test", ("app测试", "移动端", "安卓测试", "ios测试")),
    ("perf_test", ("性能测试", "压力测试", "并发测试")),
    ("security_test", ("安全测试", "漏洞扫描", "渗透测试")),
    ("knowledge_search", ("知识库", "检索知识", "查资料")),
    ("environment_check", ("环境检查", "健康检查", "测试环境")),
)


def perceive_node(state: AgentState) -> AgentState:
    """Normalize current user input into the conversation message history."""
    user_input = state.get("user_input", "").strip()
    if not user_input:
        raise ValueError("感知节点需要 user_input。")
    messages = list(state.get("messages", []))
    if not messages or messages[-1].get("content") != user_input or messages[-1].get("role") != "user":
        messages.append(Message(role="user", content=user_input))
    result = dict(state)
    result["messages"] = messages
    return result


def _extract_entities(text: str) -> dict[str, Any]:
    """Extract conservative identifiers and URLs without interpreting secrets."""
    urls = re.findall(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", text)
    document_ids = re.findall(r"(?:文档|document)[：:# ]?([0-9a-fA-F-]{8,})", text, re.IGNORECASE)
    return {"urls": urls, "document_ids": document_ids}


def understand_node(state: AgentState) -> AgentState:
    """Classify intent and return entities plus actionable clarification prompts."""
    text = state.get("user_input", "").strip()
    if not text:
        raise ValueError("理解节点需要 user_input。")
    lowered = text.casefold()
    intent = "other"
    for candidate, keywords in INTENT_KEYWORDS:
        if any(keyword.casefold() in lowered for keyword in keywords):
            intent = candidate
            break
    questions: list[str] = []
    if intent in {"api_test", "ui_test", "app_test", "perf_test", "security_test"} and not state.get("selected_environment"):
        questions.append("请选择要执行测试的环境。")
    if intent == "requirement_analysis" and not state.get("requirement_document_id"):
        questions.append("请提供需求文档。")
    result = dict(state)
    result["intent"] = intent
    result["entities"] = _extract_entities(text)
    result["clarified_questions"] = questions
    return result
