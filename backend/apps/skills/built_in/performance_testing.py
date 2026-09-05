"""Built-in performance testing Skill."""
from typing import Any, Mapping
from apps.skills.base import BaseSkill

class PerformanceTestingSkill(BaseSkill):
    """Choose a performance engine and return an execution plan."""
    name = "性能测试"; version = "1.0.0"
    @property
    def description(self) -> str: return "根据并发和脚本条件规划 JMeter 或 Locust 性能测试。"
    def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return a deterministic engine selection without starting a load test."""
        users = payload.get("concurrency", 1)
        if not isinstance(users, int) or users < 1: raise ValueError("性能测试 concurrency 必须是正整数。")
        engine = payload.get("engine") or ("locust" if users > 50000 else "jmeter" if payload.get("jmx") else "locust")
        if engine not in {"jmeter", "locust"}: raise ValueError("性能测试 engine 必须是 jmeter 或 locust。")
        return {"skill": self.name, "version": self.version, "status": "planned", "engine": engine, "concurrency": users}
