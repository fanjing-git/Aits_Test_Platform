from django.test import SimpleTestCase
from apps.agents.state import new_agent_state, validate_agent_state


class AgentStateTests(SimpleTestCase):
    def test_factory_initializes_all_orchestration_sections(self):
        state = new_agent_state("测试登录", "project-1", "user-1")
        validate_agent_state(state)
        self.assertEqual(state["execution_status"], "pending")
        self.assertEqual(state["messages"][0]["role"], "user")
        self.assertTrue(state["conversation_id"])

    def test_factory_rejects_missing_identity(self):
        with self.assertRaises(ValueError): new_agent_state("", "project-1", "user-1")

    def test_validation_rejects_bad_lifecycle_interrupt_and_message(self):
        state = new_agent_state("测试", "p", "u")
        state["execution_status"] = "unknown"
        with self.assertRaises(ValueError): validate_agent_state(state)
        state["execution_status"] = "pending"; state["interrupt_signal"] = "resume"
        with self.assertRaises(ValueError): validate_agent_state(state)
        state["interrupt_signal"] = ""; state["messages"] = [{"role": "robot", "content": "x"}]
        with self.assertRaises(ValueError): validate_agent_state(state)
