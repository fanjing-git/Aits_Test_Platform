"""Canonical contracts for executable Skill chains.

The chain contract is deliberately independent from the execution runtime.  It
lets configuration, REST clients, and later runtime tasks exchange the same
validated shape without treating a list of Skill IDs as an executable plan.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


CHAIN_SCHEMA_VERSION = "skill-chain-v1"
_NODE_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_NODE_TYPES = {"skill", "human_gate", "merge"}
_ROLES = {"core", "related"}
_EXECUTION_MODES = {"sequential", "parallel"}
_HUMAN_GATES = {"none", "required", "optional"}
_FAILURE_STRATEGIES = {"stop", "continue", "retry"}
_MERGE_STRATEGIES = {"required_only", "all", "best_effort"}


class SkillChainContractError(ValueError):
    """Raised when a Skill-chain definition is incomplete or unsafe."""


def _object(value: Any, label: str) -> dict[str, Any]:
    """Return a JSON object or raise a user-safe contract error."""
    if not isinstance(value, dict):
        raise SkillChainContractError(f"{label} must be a JSON object")
    return dict(value)


def _string(value: Any, label: str, *, required: bool = True) -> str:
    """Validate one bounded non-empty string."""
    if not isinstance(value, str) or not value.strip():
        if required:
            raise SkillChainContractError(f"{label} must be a non-empty string")
        return ""
    return value.strip()


def _bounded_integer(value: Any, label: str, *, minimum: int, maximum: int) -> int:
    """Validate one bounded integer used by runtime governance."""
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise SkillChainContractError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _schema(value: Any, label: str) -> dict[str, Any]:
    """Validate an input or output JSON Schema envelope."""
    schema = _object(value, label)
    schema_type = schema.get("type")
    if schema_type is not None and (
        not isinstance(schema_type, str)
        or schema_type not in {"object", "array", "string", "number", "boolean", "null"}
    ):
        raise SkillChainContractError(f"{label}.type is not supported")
    return schema


def _node(value: Any, node_ids: set[str]) -> dict[str, Any]:
    """Validate and normalize one chain node."""
    raw = _object(value, "node")
    node_id = _string(raw.get("node_id"), "node.node_id")
    if not _NODE_ID_PATTERN.fullmatch(node_id):
        raise SkillChainContractError("node.node_id must use letters, numbers, '_' or '-'")
    if node_id in node_ids:
        raise SkillChainContractError(f"duplicate node_id: {node_id}")
    node_type = _string(raw.get("node_type", "skill"), "node.node_type")
    if node_type not in _NODE_TYPES:
        raise SkillChainContractError(f"node.node_type is not supported: {node_type}")
    role = _string(raw.get("role", "related"), "node.role")
    if role not in _ROLES:
        raise SkillChainContractError(f"node.role is not supported: {role}")
    execution_mode = _string(raw.get("execution_mode", "sequential"), "node.execution_mode")
    if execution_mode not in _EXECUTION_MODES:
        raise SkillChainContractError(f"node.execution_mode is not supported: {execution_mode}")
    human_gate = _string(raw.get("human_gate", "none"), "node.human_gate")
    if human_gate not in _HUMAN_GATES:
        raise SkillChainContractError(f"node.human_gate is not supported: {human_gate}")
    failure_strategy = _string(raw.get("failure_strategy", "stop"), "node.failure_strategy")
    if failure_strategy not in _FAILURE_STRATEGIES:
        raise SkillChainContractError(f"node.failure_strategy is not supported: {failure_strategy}")
    dependencies = raw.get("depends_on", [])
    if not isinstance(dependencies, list) or any(not isinstance(item, str) or not item.strip() for item in dependencies):
        raise SkillChainContractError("node.depends_on must be a string array")
    normalized_dependencies = [item.strip() for item in dependencies]
    if len(normalized_dependencies) != len(set(normalized_dependencies)):
        raise SkillChainContractError("node.depends_on cannot contain duplicates")
    skill_id = _string(raw.get("skill_id"), "node.skill_id", required=False) or None
    if node_type == "skill" and skill_id is None:
        raise SkillChainContractError("skill nodes require skill_id")
    if node_type != "skill" and skill_id is not None:
        raise SkillChainContractError("only skill nodes may declare skill_id")
    if role == "core" and node_type != "skill":
        raise SkillChainContractError("only skill nodes may have the core role")
    version_range = raw.get("skill_version_range", "*")
    version_range = _string(version_range, "node.skill_version_range")
    if any(character.isspace() for character in version_range):
        raise SkillChainContractError("node.skill_version_range cannot contain whitespace")
    return {
        "node_id": node_id,
        "node_type": node_type,
        "role": role,
        "skill_id": skill_id,
        "skill_version_range": version_range,
        "execution_mode": execution_mode,
        "input_schema": _schema(raw.get("input_schema", {}), "node.input_schema"),
        "output_schema": _schema(raw.get("output_schema", {}), "node.output_schema"),
        "human_gate": human_gate,
        "failure_strategy": failure_strategy,
        "depends_on": normalized_dependencies,
        "timeout_seconds": _bounded_integer(raw.get("timeout_seconds", 30), "node.timeout_seconds", minimum=1, maximum=86400),
        "max_retries": _bounded_integer(raw.get("max_retries", 0), "node.max_retries", minimum=0, maximum=10),
    }


def validate_skill_chain_definition(value: Any) -> dict[str, Any]:
    """Validate and return the canonical executable Skill-chain definition.

    A legacy ``skill_ids``/``skills`` list is intentionally rejected when no
    node contract is supplied.  This prevents later runtime tasks from
    guessing execution order, schemas, permissions, or human gates.
    """
    raw = _object(value, "definition")
    if "nodes" not in raw:
        if "skill_ids" in raw or "skills" in raw:
            raise SkillChainContractError("Skill chain must define nodes; a Skill ID list is not a complete chain")
        raise SkillChainContractError("definition.nodes is required")
    nodes = raw.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise SkillChainContractError("definition.nodes must contain at least one node")
    node_ids: set[str] = set()
    canonical_nodes: list[dict[str, Any]] = []
    for item in nodes:
        normalized = _node(item, node_ids)
        canonical_nodes.append(normalized)
        node_ids.add(normalized["node_id"])
    for item in canonical_nodes:
        unknown = sorted(set(item["depends_on"]) - node_ids)
        if unknown:
            raise SkillChainContractError(f"node {item['node_id']} depends on unknown nodes: {unknown}")
        if item["node_id"] in item["depends_on"]:
            raise SkillChainContractError(f"node {item['node_id']} cannot depend on itself")
    _validate_dependency_graph(canonical_nodes)
    core_nodes = [
        item for item in canonical_nodes
        if item["node_type"] == "skill" and item["role"] == "core"
    ]
    if len(core_nodes) != 1:
        raise SkillChainContractError("a Skill chain must contain exactly one core Skill node")
    merge_strategy = _string(raw.get("merge_strategy", "required_only"), "definition.merge_strategy")
    if merge_strategy not in _MERGE_STRATEGIES:
        raise SkillChainContractError(f"definition.merge_strategy is not supported: {merge_strategy}")
    return {
        "schema_version": CHAIN_SCHEMA_VERSION,
        "nodes": canonical_nodes,
        "merge_strategy": merge_strategy,
        "max_calls": _bounded_integer(raw.get("max_calls", 20), "definition.max_calls", minimum=1, maximum=1000),
        "max_runtime_seconds": _bounded_integer(raw.get("max_runtime_seconds", 300), "definition.max_runtime_seconds", minimum=1, maximum=86400),
        "max_cost_units": _bounded_integer(raw.get("max_cost_units", 0), "definition.max_cost_units", minimum=0, maximum=1000000),
        "allowed_data_scopes": [
            _string(item, "definition.allowed_data_scopes item")
            for item in raw.get("allowed_data_scopes", [])
        ] if isinstance(raw.get("allowed_data_scopes", []), list) else _raise_list("definition.allowed_data_scopes"),
    }


def _raise_list(label: str) -> list[str]:
    """Raise a consistent error for malformed string-list policy fields."""
    raise SkillChainContractError(f"{label} must be a string array")


def _validate_dependency_graph(nodes: list[dict[str, Any]]) -> None:
    """Reject dependency cycles using a linear-time topological walk."""
    dependents: dict[str, list[str]] = {node["node_id"]: [] for node in nodes}
    remaining_dependencies = {node["node_id"]: len(node["depends_on"]) for node in nodes}
    for node in nodes:
        for dependency in node["depends_on"]:
            dependents[dependency].append(node["node_id"])

    ready = [node_id for node_id, count in remaining_dependencies.items() if count == 0]
    visited_count = 0
    while ready:
        node_id = ready.pop()
        visited_count += 1
        for dependent in dependents[node_id]:
            remaining_dependencies[dependent] -= 1
            if remaining_dependencies[dependent] == 0:
                ready.append(dependent)

    if visited_count != len(nodes):
        raise SkillChainContractError("definition.nodes dependencies must be acyclic")


def legacy_skill_ids(value: Any) -> list[str]:
    """Normalize an old Skill ID list for read-only compatibility metadata."""
    if value in (None, ""):
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise SkillChainContractError("legacy_skill_ids must be a string array")
    normalized = [item.strip() for item in value]
    if len(normalized) != len(set(normalized)):
        raise SkillChainContractError("legacy_skill_ids cannot contain duplicates")
    return normalized


__all__ = [
    "CHAIN_SCHEMA_VERSION",
    "SkillChainContractError",
    "legacy_skill_ids",
    "validate_skill_chain_definition",
]
