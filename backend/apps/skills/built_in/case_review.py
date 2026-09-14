"""Built-in test case review Skill planning contract."""

from typing import Any, Mapping

from apps.skills.base import BaseSkill


class CaseReviewSkill(BaseSkill):
    """Prepare generated cases for the controlled review service."""

    name = "用例评审"
    version = "1.0.0"

    @property
    def description(self) -> str:
        """Describe the case review capability."""
        return "检查测试用例的覆盖、风险、边界和可执行性。"

    def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return a review plan; the review service remains the persistence owner."""
        cases = payload.get("cases", [])
        if not isinstance(cases, list) or not cases:
            raise ValueError("用例评审需要 cases。")
        return {
            "skill": self.name,
            "version": self.version,
            "status": "planned",
            "case_count": len(cases),
            "dimensions": ["覆盖", "风险", "边界", "可执行性"],
        }
