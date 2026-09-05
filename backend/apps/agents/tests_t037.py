from django.test import SimpleTestCase
from apps.agents.requirement import case_generation_node, case_review_node, requirement_analysis_node
from apps.agents.state import new_agent_state


class RequirementFlowTests(SimpleTestCase):
    def test_requirement_analysis_creates_auditable_structure(self):
        state = requirement_analysis_node(new_agent_state("用户可以登录系统", "p", "u"))
        self.assertEqual(state["requirement_analysis"]["summary"], "用户可以登录系统")
        self.assertIn("acceptance_points", state["requirement_analysis"])

    def test_case_generation_and_review_cover_three_categories(self):
        state = requirement_analysis_node(new_agent_state("登录功能", "p", "u")); state = case_generation_node(state); self.assertEqual(state["case_generation"]["count"], 3)
        reviewed = case_review_node(state)
        self.assertTrue(reviewed["case_generation"]["review"]["approved"])
        self.assertEqual(reviewed["case_generation"]["status"], "reviewed")

    def test_flow_rejects_missing_prerequisites(self):
        state = new_agent_state("x", "p", "u")
        with self.assertRaises(ValueError): case_generation_node(state)
        with self.assertRaises(ValueError): case_review_node(state)
        state["user_input"] = ""
        with self.assertRaises(ValueError): requirement_analysis_node(state)

    def test_review_reports_missing_case_category(self):
        state = new_agent_state("登录", "p", "u"); state["case_generation"] = {"cases": [{"type": "positive"}], "count": 1, "status": "draft"}
        reviewed = case_review_node(state)
        self.assertFalse(reviewed["case_generation"]["review"]["approved"])
        self.assertEqual(reviewed["case_generation"]["review"]["missing_types"], ["boundary", "negative"])
