"""Business-facing Skill orchestration without exposing raw permissions to users."""

from dataclasses import dataclass
import re
from typing import Any, Mapping

from apps.skills.manager import SkillManager
from apps.skills.runtime import SkillRuntimeError
from apps.skills.built_in import (
    AiTestingSkill,
    AppTestingSkill,
    ApiTestingSkill,
    CaseGenerationSkill,
    CaseReviewSkill,
    PerformanceTestingSkill,
    RequirementAnalysisSkill,
    SecurityTestingSkill,
    ScreenshotRecognitionSkill,
    register_builtin_skills,
)


INTENT_SKILLS: dict[str, str] = {
    "requirement_analysis": RequirementAnalysisSkill.name,
    "case_generation": CaseGenerationSkill.name,
    "case_gen": CaseGenerationSkill.name,
    "case_review": CaseReviewSkill.name,
    "api_test": ApiTestingSkill.name,
    "ai_test": AiTestingSkill.name,
    "perf_test": PerformanceTestingSkill.name,
    "app_test": AppTestingSkill.name,
    "security_test": SecurityTestingSkill.name,
    "ui_test": ScreenshotRecognitionSkill.name,
}


@dataclass(frozen=True)
class SkillExecution:
    """A safe, serializable result of one business Skill invocation."""

    skill: str
    version: str
    status: str
    result: dict[str, Any] | None = None
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Return a state-safe representation without secrets or raw permissions."""
        payload: dict[str, Any] = {
            "skill": self.skill,
            "version": self.version,
            "status": self.status,
        }
        if self.result is not None:
            payload["result"] = self.result
        if self.message:
            payload["message"] = self.message
        return payload


class SkillExecutionService:
    """Invoke registered Skills from business flows with validated payloads.

    The service owns Skill selection and payload construction. Callers provide
    business context such as a requirement or target; they never provide a raw
    permission name. Third-party source code is not loaded by this service.
    """

    def __init__(self, manager: SkillManager | None = None) -> None:
        self.manager = manager or SkillManager()
        if not self.manager._registry:
            register_builtin_skills(self.manager)

    @staticmethod
    def _url_from_text(text: str) -> str:
        """Extract the first explicit HTTP(S) target from user context."""
        match = re.search(r"https?://[^\s]+", text)
        return match.group(0).rstrip(".,;，。；") if match else ""

    @staticmethod
    def _platform_from_text(text: str) -> str:
        """Extract a supported mobile platform without guessing unsupported values."""
        lowered = text.casefold()
        if "android" in lowered or "安卓" in text:
            return "android"
        if "ios" in lowered or "iphone" in lowered:
            return "ios"
        return ""

    def _payload(self, intent: str, state: Mapping[str, Any]) -> dict[str, Any] | None:
        """Build a business payload or return None when clarification is required."""
        text = str(state.get("user_input", "")).strip()
        entities = state.get("entities") if isinstance(state.get("entities"), Mapping) else {}
        urls = entities.get("urls") if isinstance(entities, Mapping) else []
        endpoint = urls[0] if isinstance(urls, list) and urls and isinstance(urls[0], str) else self._url_from_text(text)
        if intent == "requirement_analysis":
            return {"requirement": text}
        if intent in {"case_generation", "case_gen"}:
            analysis = state.get("requirement_analysis")
            summary = analysis.get("summary") if isinstance(analysis, Mapping) else text
            return {"requirement": str(summary or text).strip()}
        if intent == "case_review":
            cases = state.get("cases")
            return {"cases": cases} if isinstance(cases, list) and cases else None
        if intent == "api_test":
            return {"endpoint": endpoint} if endpoint else None
        if intent == "ai_test":
            return {"prompt": text}
        if intent == "perf_test":
            return {"concurrency": state.get("concurrency", 1), "engine": state.get("engine")}
        if intent == "app_test":
            platform = str(state.get("platform") or self._platform_from_text(text)).strip().lower()
            return {"platform": platform} if platform else None
        if intent == "security_test":
            return {"target": endpoint, "authorized": state.get("security_authorized") is True} if endpoint else None
        if intent == "ui_test":
            image = str(state.get("image") or endpoint).strip()
            return {"image": image} if image else None
        return None

    def execute(self, intent: str, state: Mapping[str, Any]) -> SkillExecution | None:
        """Execute the Skill for an intent, returning clarification instead of prompting."""
        skill_name = INTENT_SKILLS.get(intent)
        if not skill_name:
            return None
        payload = self._payload(intent, state)
        if payload is None:
            return SkillExecution(skill_name, "1.0.0", "needs_input", message="业务参数不足，等待用户在对应功能页面补充。")
        try:
            skill = self.manager.load(skill_name, project_id=state.get("project_id"))
            result = skill.execute(payload)
        except (LookupError, ValueError, PermissionError, SkillRuntimeError) as exc:
            return SkillExecution(skill_name, "1.0.0", "failed", message=str(exc))
        except Exception:
            return SkillExecution(skill_name, "1.0.0", "failed", message="Skill 执行失败，请查看业务模块错误详情。")
        return SkillExecution(skill_name, getattr(skill, "version", "1.0.0"), "completed", result=result)

    def execute_state(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """Execute the current intent and append a structured result to agent state."""
        result = self.execute(str(state.get("intent", "")), state)
        updated = dict(state)
        if result is None:
            return updated
        results = list(state.get("execution_results", []))
        results.append(result.as_dict())
        updated["execution_results"] = results
        if result.status == "completed":
            updated["execution_status"] = "completed"
        elif result.status in {"failed", "needs_input"}:
            updated["execution_status"] = "failed" if result.status == "failed" else "paused"
            updated["error_message"] = result.message
        return updated


__all__ = ["INTENT_SKILLS", "SkillExecution", "SkillExecutionService"]
