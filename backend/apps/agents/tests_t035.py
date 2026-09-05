from unittest.mock import patch
from django.test import TestCase
from apps.agents.planning import plan_node, retrieve_node
from apps.agents.state import new_agent_state
from apps.knowledge.retrieval import RetrievalHit
from uuid import uuid4


class AgentPlanningTests(TestCase):
    @patch("apps.agents.planning.retrieve")
    def test_retrieve_node_serializes_provenance(self, mocked):
        mocked.return_value = [RetrievalHit("e1", "kb1", "d1", "登录必须鉴权", 0.9)]
        state = retrieve_node(new_agent_state("查询登录鉴权", "p", "u"))
        self.assertEqual(state["knowledge_context"][0]["document_id"], "d1")
        self.assertEqual(state["knowledge_context"][0]["score"], 0.9)

    def test_plan_node_recommends_builtin_skill_and_creates_order(self):
        state = new_agent_state("请做接口测试", str(uuid4()), "u"); state["intent"] = "api_test"
        planned = plan_node(state)
        self.assertIn("接口测试", planned["selected_skills"])
        self.assertEqual(planned["plan"]["status"], "ready")
        self.assertEqual(planned["execution_order"], planned["selected_skills"])

    def test_plan_node_uses_intent_fallback_when_no_trigger_match(self):
        state = new_agent_state("执行这个任务", str(uuid4()), "u"); state["intent"] = "case_gen"
        planned = plan_node(state)
        self.assertEqual(planned["selected_skills"], ["用例生成"])

    def test_nodes_reject_missing_query(self):
        state = new_agent_state("x", "p", "u"); state["user_input"] = ""
        with self.assertRaises(ValueError): retrieve_node(state)
