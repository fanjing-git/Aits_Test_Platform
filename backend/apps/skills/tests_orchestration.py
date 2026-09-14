"""Focused tests for business-facing Skill orchestration."""

from uuid import uuid4

from django.test import TestCase

from apps.agents.graph import build_agent_graph
from apps.agents.state import new_agent_state
from apps.skills.orchestration import SkillExecutionService


class SkillOrchestrationTests(TestCase):
    """Ensure business flows call Skills without raw permission prompts."""

    def test_requirement_flow_records_automatic_skill_execution(self) -> None:
        state = new_agent_state("需求内容", str(uuid4()), "user")
        state["intent"] = "requirement_analysis"
        result = SkillExecutionService().execute_state(state)
        self.assertEqual(result["execution_results"][0]["skill"], "需求分析")
        self.assertEqual(result["execution_results"][0]["status"], "completed")

    def test_missing_business_parameter_pauses_without_permission_input(self) -> None:
        service = SkillExecutionService()
        result = service.execute("api_test", {"user_input": "请做接口测试", "project_id": str(uuid4())})
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "needs_input")
        self.assertNotIn("permission", result.message.casefold())

    def test_all_existing_test_intents_use_the_shared_execution_boundary(self) -> None:
        service = SkillExecutionService()
        contexts = {
            "api_test": {"user_input": "请测试 https://example.test/health"},
            "ai_test": {"user_input": "评估模型回答"},
            "perf_test": {"user_input": "性能测试", "concurrency": 10},
            "app_test": {"user_input": "执行 Android APP 测试"},
            "security_test": {"user_input": "安全测试 https://example.test"},
            "ui_test": {"user_input": "截图识别", "image": "local.png"},
        }
        for intent, context in contexts.items():
            with self.subTest(intent=intent):
                result = service.execute(intent, {**context, "project_id": str(uuid4())})
                self.assertIsNotNone(result)
                self.assertIn(result.status, {"completed", "failed"})
