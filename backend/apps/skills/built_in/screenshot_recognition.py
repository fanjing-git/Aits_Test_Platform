"""Built-in screenshot recognition Skill."""
from typing import Any, Mapping
from apps.skills.base import BaseSkill

class ScreenshotRecognitionSkill(BaseSkill):
    """Describe screenshot analysis work without invoking an image service."""
    name = "截图识别"; version = "1.0.0"
    @property
    def description(self) -> str: return "规划截图中的界面元素和视觉问题识别。"
    def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return a screenshot analysis plan."""
        image = str(payload.get("image", "")).strip()
        if not image: raise ValueError("截图识别需要 image。")
        return {"skill": self.name, "version": self.version, "status": "planned", "image": image, "checks": ["layout", "text", "visual_regression"]}
