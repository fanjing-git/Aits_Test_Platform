"""Controlled execution boundary for persisted Skills."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Mapping
from apps.skills.models import Skill

class SkillRuntimeError(Exception):
    """A safe, user-facing runtime failure."""

def _validate_schema(value: Any, schema: dict, label: str) -> None:
    if not isinstance(schema, dict):
        raise SkillRuntimeError(f"{label} schema must be an object")
    expected = schema.get("type")
    if expected == "object" and not isinstance(value, dict): raise SkillRuntimeError(f"{label} must be an object")
    if expected == "array" and not isinstance(value, list): raise SkillRuntimeError(f"{label} must be an array")
    if expected == "string" and not isinstance(value, str): raise SkillRuntimeError(f"{label} must be a string")
    if expected == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)): raise SkillRuntimeError(f"{label} must be a number")
    if expected == "boolean" and not isinstance(value, bool): raise SkillRuntimeError(f"{label} must be a boolean")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value: raise SkillRuntimeError(f"input missing required field: {key}")
        for key, child in schema.get("properties", {}).items():
            if key in value: _validate_schema(value[key], child, f"{label}.{key}")

def _configured_execute(skill: Skill, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic custom runtime; it never evaluates user supplied Python."""
    return {"skill": skill.name, "version": skill.version, "status": "completed", "echo": dict(payload), "runtime": skill.runtime_key}

def execute_skill(skill: Skill, payload: Mapping[str, Any], timeout: int | None = None) -> dict[str, Any]:
    if skill.status != Skill.Status.ENABLED: raise SkillRuntimeError("skill is disabled")
    if not isinstance(payload, dict): raise SkillRuntimeError("input must be a JSON object")
    _validate_schema(payload, skill.input_schema or {"type": "object"}, "input")
    seconds = max(1, min(int(timeout or skill.timeout_seconds or 30), 300))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_configured_execute, skill, payload)
        try: result = future.result(timeout=seconds)
        except FutureTimeout as exc:
            future.cancel(); raise SkillRuntimeError(f"skill execution timed out after {seconds}s") from exc
        except Exception as exc: raise SkillRuntimeError("skill execution failed") from exc
    _validate_schema(result, skill.output_schema or {"type": "object"}, "output")
    return result
