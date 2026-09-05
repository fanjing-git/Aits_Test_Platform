"""Built-in API testing Skill."""
from typing import Any, Mapping
from apps.skills.base import BaseSkill


class ApiTestingSkill(BaseSkill):
    """Plan API checks from a structured request without making network calls."""
    name = "接口测试"
    version = "1.0.0"

    @property
    def description(self) -> str:
        """Describe the API testing capability."""
        return "根据接口定义生成请求、响应和断言检查计划。"

    def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return a safe deterministic API test plan."""
        endpoint = str(payload.get("endpoint", "")).strip()
        if not endpoint:
            raise ValueError("接口测试需要 endpoint。")
        return {"skill": self.name, "version": self.version, "status": "planned", "endpoint": endpoint, "checks": ["status_code", "response_schema"]}
