from django.test import SimpleTestCase
from apps.agents.reporting import learn_node, reflect_node, report_node
from apps.agents.state import new_agent_state


class AgentReportingTests(SimpleTestCase):
    def test_reflect_marks_successful_results_reportable(self):
        state = new_agent_state("接口测试", "p", "u"); state["execution_results"] = [{"status": "passed"}]
        reflected = reflect_node(state)
        self.assertFalse(reflected["needs_replan"]); self.assertTrue(reflected["should_learn"]); self.assertTrue(reflected["should_report"])

    def test_reflect_requests_replan_for_failures(self):
        state = new_agent_state("测试", "p", "u"); state["execution_results"] = [{"status": "failed"}, {"status": "passed"}]
        reflected = reflect_node(state)
        self.assertTrue(reflected["needs_replan"]); self.assertEqual(reflected["analysis"]["failure_count"], 1)

    def test_learn_is_reviewable_and_report_contains_trace(self):
        state = new_agent_state("测试", "project-1", "user-1"); state["analysis"] = {"summary": "结果"}; state["intent"] = "api_test"; state["selected_skills"] = ["接口测试"]
        learned = learn_node(state); self.assertTrue(learned["analysis"]["learning_candidate"]["requires_review"])
        report = report_node(learned)["final_report"]
        self.assertEqual(report["conversation_id"], state["conversation_id"]); self.assertEqual(report["selected_skills"], ["接口测试"]); self.assertTrue(report["generated_at"])
