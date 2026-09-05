"""Small dependency-light graph orchestrator for agent state transitions."""
from typing import Callable
from apps.agents.decision import decide_node
from apps.agents.nodes import perceive_node, understand_node
from apps.agents.planning import plan_node, retrieve_node
from apps.agents.reporting import learn_node, reflect_node, report_node
from apps.agents.requirement import case_generation_node, case_review_node, requirement_analysis_node
from apps.agents.state import AgentState


class AgentGraph:
    """Execute the deterministic node pipeline and return final state."""
    def __init__(self) -> None:
        self.nodes: tuple[Callable[[AgentState], AgentState], ...] = (perceive_node, understand_node, retrieve_node, plan_node, decide_node)

    def invoke(self, state: AgentState) -> AgentState:
        """Run perception through reporting, honoring pause/cancel routes."""
        current = state
        for node in self.nodes:
            current = node(current)
        if current.get("route") == "requirement_analysis":
            current = requirement_analysis_node(current); current = case_generation_node(current); current = case_review_node(current)
        if current.get("route") not in {"wait_for_input", "cancelled"}:
            current = reflect_node(current); current = learn_node(current); current = report_node(current)
        return current


def build_agent_graph() -> AgentGraph:
    """Build a fresh graph with no shared mutable execution state."""
    return AgentGraph()
