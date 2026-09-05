"""Built-in test case generation Skill."""
from typing import Any, Mapping
from apps.skills.base import BaseSkill


class CaseGenerationSkill(BaseSkill):
    """Generate a structured case-generation plan from requirements."""
    name = "用例生成"
    version = "1.0.0"

    @property
    def description(self) -> str:
        """Describe the case generation capability."""
        return "从需求和风险信息整理测试用例生成计划。"

    def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return a deterministic generation plan without writing test assets."""
        requirement = str(payload.get("requirement", "")).strip()
        if not requirement:
            raise ValueError("用例生成需要 requirement。")
        return {"skill": self.name, "version": self.version, "status": "planned", "requirement": requirement, "case_types": ["positive", "negative", "boundary"]}
