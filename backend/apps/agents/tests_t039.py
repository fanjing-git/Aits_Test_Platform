from django.test import TestCase
from apps.agents.graph import build_agent_graph
from apps.agents.state import new_agent_state
from apps.agents.tasks import run_agent_graph
from uuid import uuid4


class AgentGraphTests(TestCase):
    def test_graph_runs_requirement_flow_to_report(self):
        state = new_agent_state("请分析需求并生成用例", str(uuid4()), "u"); state["intent"] = "requirement_analysis"
        result = build_agent_graph().invoke(state)
        self.assertEqual(result["route"], "requirement_analysis")
        self.assertEqual(result["case_generation"]["status"], "reviewed")
        self.assertIn("final_report", result)

    def test_graph_honors_pause_and_celery_task_returns_safe_failure(self):
        state = new_agent_state("请做接口测试", str(uuid4()), "u"); state["interrupt_signal"] = "pause"
        result = build_agent_graph().invoke(state)
        self.assertEqual(result["route"], "wait_for_input"); self.assertEqual(result["execution_status"], "paused")
        failed = run_agent_graph.apply(args=[{"user_input":""}]).get()
        self.assertEqual(failed["execution_status"], "failed"); self.assertTrue(failed["error_message"])

    def test_graph_factory_is_independent(self):
        self.assertIsNot(build_agent_graph(), build_agent_graph())
