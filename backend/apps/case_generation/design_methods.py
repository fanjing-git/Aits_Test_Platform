"""Canonical test-design method names shared by generation and model validation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DESIGN_METHOD_LABELS = {
    "positive_flow": "正向流程",
    "equivalence_class": "等价类",
    "boundary_value": "边界值",
    "error_guessing": "错误猜测法",
    "cause_effect_graph": "因果图",
    "state_transition": "状态转换",
    "security": "安全",
    "performance": "性能",
    "linkage": "联动",
    "regression_compatibility": "回归兼容",
}

_ALIASES = {
    "positive": "positive_flow",
    "positive_flow": "positive_flow",
    "normal": "positive_flow",
    "正常": "positive_flow",
    "正向": "positive_flow",
    "正常流程": "positive_flow",
    "equivalence": "equivalence_class",
    "equivalence_class": "equivalence_class",
    "equivalence-class": "equivalence_class",
    "等价类": "equivalence_class",
    "等价类划分": "equivalence_class",
    "boundary": "boundary_value",
    "boundary_value": "boundary_value",
    "boundary-value": "boundary_value",
    "边界": "boundary_value",
    "边界值": "boundary_value",
    "negative": "error_guessing",
    "exception": "error_guessing",
    "error_guessing": "error_guessing",
    "error-guessing": "error_guessing",
    "error_guess": "error_guessing",
    "异常": "error_guessing",
    "错误猜测法": "error_guessing",
    "security": "security",
    "安全": "security",
    "cause_effect": "cause_effect_graph",
    "cause-effect": "cause_effect_graph",
    "cause_effect_graph": "cause_effect_graph",
    "cause-effect-graph": "cause_effect_graph",
    "因果图": "cause_effect_graph",
    "state": "state_transition",
    "state_transition": "state_transition",
    "state-transition": "state_transition",
    "状态": "state_transition",
    "状态转换": "state_transition",
    "performance": "performance",
    "concurrency": "performance",
    "性能": "performance",
    "联动": "linkage",
    "link": "linkage",
    "linkage": "linkage",
    "回归": "regression_compatibility",
    "regression": "regression_compatibility",
    "regression_compatibility": "regression_compatibility",
    "regression-compatibility": "regression_compatibility",
}


def normalize_design_method(value: Any, *, default: str = "positive_flow") -> str:
    """Return one canonical test-design method for a raw type or method value."""
    raw = str(value or "").strip().casefold()
    return _ALIASES.get(raw, default)


def point_design_method(point: Mapping[str, Any] | Any) -> str:
    """Resolve a test point's explicit method, falling back to its legacy type."""
    if not isinstance(point, Mapping):
        return "positive_flow"
    return normalize_design_method(
        point.get("test_design_method") or point.get("design_method") or point.get("type")
    )


def legacy_case_type(method: str, *, linkage: bool = False) -> str:
    """Map a design method to the legacy four-category case type."""
    if linkage or method == "linkage":
        return "linkage"
    if method in {"boundary_value", "state_transition", "performance"}:
        return "boundary"
    if method in {"error_guessing", "security"}:
        return "negative"
    return "positive"


def design_method_label(value: Any) -> str:
    """Return a user-facing Chinese label for a canonical or legacy method."""
    method = normalize_design_method(value)
    return DESIGN_METHOD_LABELS[method]


__all__ = [
    "DESIGN_METHOD_LABELS",
    "design_method_label",
    "legacy_case_type",
    "normalize_design_method",
    "point_design_method",
]
