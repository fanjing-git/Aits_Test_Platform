"""Contracts implemented by executable Skills."""
from abc import ABC, abstractmethod
from typing import Any, Mapping

class BaseSkill(ABC):
    """Minimal runtime contract shared by built-in and custom Skills."""
    name: str = ""
    version: str = "1.0.0"
    @property
    @abstractmethod
    def description(self) -> str:
        """Return a human-readable description."""
    @abstractmethod
    def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Execute with validated input and return structured output."""
    def manifest(self) -> dict[str, Any]:
        """Return stable metadata for registry discovery."""
        return {"name": self.name, "version": self.version, "description": self.description}
