from django.test import SimpleTestCase
from apps.agents.nodes import perceive_node, understand_node
from apps.agents.state import new_agent_state


class AgentUnderstandingTests(SimpleTestCase):
    def test_perceive_normalizes_message_and_is_idempotent(self):
        state = new_agent_state("请做接口测试", "p", "u")
        first = perceive_node(state); second = perceive_node(first)
        self.assertEqual(len(first["messages"]), 1)
        self.assertEqual(first["messages"], second["messages"])

    def test_understand_classifies_supported_intents(self):
        cases = {"请分析需求文档": "requirement_analysis", "生成测试用例": "case_gen", "检查接口": "api_test", "做压力测试": "perf_test", "进行安全测试": "security_test", "检索知识库": "knowledge_search"}
        for text, expected in cases.items():
            state = understand_node(new_agent_state(text, "p", "u"))
            self.assertEqual(state["intent"], expected)

    def test_understand_extracts_urls_and_requests_environment(self):
        state = understand_node(new_agent_state("请测试 https://example.test/login 接口", "p", "u"))
        self.assertEqual(state["entities"]["urls"], ["https://example.test/login"])
        self.assertTrue(state["clarified_questions"])
        state = dict(state); state["selected_environment"] = "test"; self.assertFalse(understand_node(state)["clarified_questions"])

    def test_requirement_analysis_requests_document_and_unknown_is_safe(self):
        state = understand_node(new_agent_state("请分析需求", "p", "u"))
        self.assertIn("请提供需求文档。", state["clarified_questions"])
        self.assertEqual(understand_node(new_agent_state("你好", "p", "u"))["intent"], "other")

    def test_nodes_reject_missing_input(self):
        state = new_agent_state("x", "p", "u"); state["user_input"] = ""
        with self.assertRaises(ValueError): perceive_node(state)
        with self.assertRaises(ValueError): understand_node(state)
