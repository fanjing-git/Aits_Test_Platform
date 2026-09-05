"""Knowledge retrieval and Skill planning nodes."""
from typing import Any

from apps.agents.state import AgentState
from apps.knowledge.retrieval import retrieve
from apps.skills.built_in import register_builtin_skills
from apps.skills.manager import SkillManager


def retrieve_node(state: AgentState) -> AgentState:
    """Retrieve approved project knowledge and write safe provenance into state."""
    query = state.get("user_input", "").strip()
    if not query:
        raise ValueError("检索节点需要 user_input。")
    entities = state.get("entities", {})
    base_ids = entities.get("knowledge_base_ids") if isinstance(entities, dict) else None
    hits = retrieve(query, base_ids)
    result = dict(state)
    result["knowledge_context"] = [{"embedding_id": hit.embedding_id, "knowledge_base_id": hit.knowledge_base_id, "document_id": hit.document_id, "content": hit.content, "score": hit.score} for hit in hits]
    return result


def plan_node(state: AgentState, manager: SkillManager | None = None) -> AgentState:
    """Recommend Skills for the understood intent and create an execution order."""
    intent = state.get("intent", "other")
    manager = manager or SkillManager()
    if not manager._registry:
        register_builtin_skills(manager)
    matches = manager.recommend(state.get("user_input", ""), project_id=state.get("project_id"))
    selected = [match.skill.name for match in matches]
    if not selected and intent not in {"", "other"}:
        selected = {"api_test":"接口测试", "ai_test":"AI测试", "case_gen":"用例生成", "perf_test":"性能测试", "app_test":"APP测试", "security_test":"安全测试"}.get(intent, [])
        selected = [selected] if isinstance(selected, str) else selected
    result = dict(state)
    result["selected_skills"] = selected
    result["execution_order"] = selected.copy()
    result["plan"] = {"intent": intent, "knowledge_count": len(state.get("knowledge_context", [])), "skills": selected, "status": "ready"}
    return result
