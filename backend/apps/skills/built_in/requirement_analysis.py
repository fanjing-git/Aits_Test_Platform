"""Built-in requirement analysis Skill planning contract."""

from typing import Any, Mapping

from apps.skills.base import BaseSkill


class RequirementAnalysisSkill(BaseSkill):
    """Prepare the requirement context for the controlled analysis pipeline."""

    name = "需求分析"
    version = "1.0.0"

    @property
    def description(self) -> str:
        """Describe the requirement analysis capability."""
        return "整理需求上下文，识别功能、角色、验收条件和风险。"

    def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return a structured analysis plan; persistence remains in the requirement service."""
        requirement = str(payload.get("requirement", "")).strip()
        if not requirement:
            raise ValueError("需求分析需要 requirement。")
        return {
            "skill": self.name,
            "version": self.version,
            "status": "planned",
            "dimensions": ["功能拆解", "角色", "验收条件", "风险"],
            "requirement_length": len(requirement),
        }
