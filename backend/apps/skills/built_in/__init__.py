"""Built-in Skills shipped with the platform."""
from apps.skills.built_in.api_testing import ApiTestingSkill
from apps.skills.built_in.ai_testing import AiTestingSkill
from apps.skills.built_in.case_generation import CaseGenerationSkill
from apps.skills.built_in.performance_testing import PerformanceTestingSkill
from apps.skills.built_in.app_testing import AppTestingSkill
from apps.skills.built_in.security_testing import SecurityTestingSkill
from apps.skills.built_in.screenshot_recognition import ScreenshotRecognitionSkill

BUILT_IN_SKILLS = (ApiTestingSkill, AiTestingSkill, CaseGenerationSkill, PerformanceTestingSkill, AppTestingSkill, SecurityTestingSkill, ScreenshotRecognitionSkill)


def register_builtin_skills(manager):
    """Register all first-batch built-ins in a SkillManager."""
    for skill_class in BUILT_IN_SKILLS:
        manager.register(skill_class)
