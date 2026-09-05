from django.test import SimpleTestCase
from apps.agents.decision import decide_node, route_for_intent
from apps.agents.state import new_agent_state


class AgentDecisionTests(SimpleTestCase):
    def test_routes_supported_intents(self):
        expectations = {"requirement_analysis":"requirement_analysis", "case_gen":"case_generation", "api_test":"api_test", "ai_test":"ai_test", "ui_test":"ui_test", "app_test":"app_test", "perf_test":"perf_test", "security_test":"security_test", "other":"reflect"}
        for intent, route in expectations.items():
            state = new_agent_state("任务", "p", "u"); state["intent"] = intent
            self.assertEqual(decide_node(state)["route"], route)

    def test_interrupt_signals_pause_or_cancel(self):
        state = new_agent_state("任务", "p", "u"); state["intent"] = "api_test"; state["interrupt_signal"] = "pause"
        self.assertEqual(decide_node(state)["execution_status"], "paused"); self.assertEqual(decide_node(state)["route"], "wait_for_input")
        state["interrupt_signal"] = "cancel"; self.assertEqual(decide_node(state)["route"], "cancelled")

    def test_unknown_intent_and_invalid_state_are_safe(self):
        self.assertEqual(route_for_intent("unknown"), "reflect")
        state = new_agent_state("任务", "p", "u")
        with self.assertRaises(ValueError): decide_node(state)
        state["intent"] = "other"; state["interrupt_signal"] = "resume"
        with self.assertRaises(ValueError): decide_node(state)
