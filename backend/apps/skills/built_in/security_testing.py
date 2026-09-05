"""Built-in security testing Skill."""
from typing import Any, Mapping
from apps.skills.base import BaseSkill

class SecurityTestingSkill(BaseSkill):
    """Plan safe security checks without attacking external systems."""
    name = "安全测试"; version = "1.0.0"
    @property
    def description(self) -> str: return "根据授权范围规划认证、输入和敏感信息安全检查。"
    def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Require an explicit authorized target and return checks."""
        target = str(payload.get("target", "")).strip()
        if not target: raise ValueError("安全测试需要 target。")
        if payload.get("authorized") is not True: raise PermissionError("安全测试需要明确的 authorized=true。")
        return {"skill": self.name, "version": self.version, "status": "planned", "target": target, "checks": ["authentication", "input_validation", "sensitive_data"]}
