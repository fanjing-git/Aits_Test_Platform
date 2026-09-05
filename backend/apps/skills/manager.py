"""Skill registration, loading, matching and recommendation services."""
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Type

from django.db.models import Q

from apps.skills.base import BaseSkill
from apps.skills.models import Skill


@dataclass(frozen=True)
class SkillMatch:
    """A Skill definition and its deterministic matching score."""

    skill: Skill
    score: int
    reason: str


class SkillManager:
    """Coordinate runtime Skill classes with persisted Skill definitions."""

    def __init__(self) -> None:
        self._registry: dict[tuple[str, str], Type[BaseSkill]] = {}

    def register(self, skill_class: Type[BaseSkill]) -> None:
        """Register a concrete Skill class by its name and version."""
        if not issubclass(skill_class, BaseSkill) or not skill_class.name.strip():
            raise TypeError("技能类必须继承 BaseSkill 并声明名称。")
        key = (skill_class.name, skill_class.version)
        if key in self._registry:
            raise ValueError(f"技能已注册：{skill_class.name} v{skill_class.version}")
        self._registry[key] = skill_class

    def load(self, name: str, version: str = "1.0.0", project_id: str | None = None) -> BaseSkill:
        """Instantiate a registered Skill after checking its persisted status and scope."""
        skill = Skill.objects.filter(name=name, version=version, status=Skill.Status.ENABLED).filter(
            Q(project_id=project_id) | Q(project_id__isnull=True)
        ).order_by("project_id").first()
        if skill is None:
            raise LookupError(f"未找到已启用技能：{name} v{version}")
        skill_class = self._registry.get((name, version))
        if skill_class is None:
            raise LookupError(f"技能运行时未注册：{name} v{version}")
        return skill_class()

    def match(self, text: str, project_id: str | None = None) -> list[SkillMatch]:
        """Match explicit trigger words and capabilities in stable score order."""
        normalized = text.strip().casefold()
        if not normalized:
            return []
        queryset = Skill.objects.filter(status=Skill.Status.ENABLED).filter(Q(project_id=project_id) | Q(project_id__isnull=True))
        matches: list[SkillMatch] = []
        for skill in queryset:
            triggers = skill.triggers if isinstance(skill.triggers, dict) else {}
            explicit = triggers.get("explicit", [])
            if isinstance(explicit, str):
                explicit = [explicit]
            words = [word.casefold() for word in explicit if isinstance(word, str) and word.strip()]
            score = sum(1 for word in words if word in normalized)
            if score:
                matches.append(SkillMatch(skill, score, "命中明确触发词"))
        return sorted(matches, key=lambda item: (-item.score, item.skill.name, item.skill.version))

    def recommend(self, text: str, project_id: str | None = None, limit: int = 3) -> list[SkillMatch]:
        """Return up to three matches, rejecting unsafe recommendation limits."""
        if not isinstance(limit, int) or not 1 <= limit <= 10:
            raise ValueError("推荐数量必须在 1 到 10 之间。")
        return self.match(text, project_id)[:limit]
