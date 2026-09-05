"""Built-in mobile application testing Skill."""
from typing import Any, Mapping
from apps.skills.base import BaseSkill

class AppTestingSkill(BaseSkill):
    """Plan Appium device coverage without connecting to a device."""
    name = "APP测试"; version = "1.0.0"
    @property
    def description(self) -> str: return "根据设备和平台信息规划移动端安装、启动与功能测试。"
    def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return a mobile test plan."""
        platform = str(payload.get("platform", "")).strip().lower()
        if platform not in {"android", "ios"}: raise ValueError("APP测试 platform 必须是 android 或 ios。")
        return {"skill": self.name, "version": self.version, "status": "planned", "platform": platform, "checks": ["install", "launch", "smoke"]}
