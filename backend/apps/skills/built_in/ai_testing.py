"""Built-in AI testing Skill."""
from typing import Any, Mapping
from apps.skills.base import BaseSkill


class AiTestingSkill(BaseSkill):
    """Plan AI response evaluation dimensions without calling a model."""
    name = "AI测试"
    version = "1.0.0"

    @property
    def description(self) -> str:
        """Describe the AI testing capability."""
        return "根据评测目标生成 AI 输出质量检查维度。"

    def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return an evaluation plan using caller-provided criteria."""
        prompt = str(payload.get("prompt", "")).strip()
        if not prompt:
            raise ValueError("AI测试需要 prompt。")
        criteria = payload.get("criteria") or ["accuracy", "relevance", "safety"]
        if not isinstance(criteria, list) or not all(isinstance(item, str) and item.strip() for item in criteria):
            raise ValueError("AI测试 criteria 必须是字符串数组。")
        return {"skill": self.name, "version": self.version, "status": "planned", "criteria": criteria, "prompt_length": len(prompt)}
