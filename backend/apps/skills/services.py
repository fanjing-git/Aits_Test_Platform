"""Domain services for Skill-chain configuration, governance and resolution."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone

if TYPE_CHECKING:
    from apps.skills.models import SkillChain


CONFIGURATION_SNAPSHOT_SCHEMA_VERSION = "skill-chain-configuration-v1"
LAYER_PRECEDENCE = ("global", "project", "feature", "instant")
LAYER_LABELS = {
    "global": "全局默认",
    "project": "项目级",
    "feature": "功能级",
    "instant": "即时指定",
}


def build_skill_chain_configuration_snapshot(
    *,
    chain: SkillChain,
    layer: str,
    project_id: UUID | str | None,
    feature_key: str,
    request_key: str,
    version_lock: str,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """Capture one layer declaration and the exact chain contract it references.

    This is a persisted configuration-layer snapshot, not the effective merged
    result. Runtime execution snapshots remain part of the later runtime task.
    """
    return {
        "snapshot_schema_version": CONFIGURATION_SNAPSHOT_SCHEMA_VERSION,
        "layer": layer,
        "project_id": str(project_id) if project_id is not None else None,
        "feature_key": feature_key or "",
        "request_key": request_key or "",
        "version_lock": version_lock or "",
        "overrides": deepcopy(overrides),
        "chain": {
            "id": str(chain.pk),
            "name": chain.name,
            "version": chain.version,
            "schema_version": chain.schema_version,
            "definition": deepcopy(chain.definition),
        },
    }


def merge_configuration_fields(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge object fields; lists and scalar values replace lower layers."""
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_configuration_fields(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _configuration_state(configuration: Any) -> dict[str, Any]:
    """Return a JSON-safe state for governance audit and rollback."""
    return {
        "chain_id": str(configuration.chain_id),
        "layer": configuration.layer,
        "project_id": str(configuration.project_id) if configuration.project_id else None,
        "feature_key": configuration.feature_key,
        "request_key": configuration.request_key,
        "version_lock": configuration.version_lock,
        "overrides": deepcopy(configuration.overrides),
        "configuration_snapshot": deepcopy(configuration.configuration_snapshot),
        "enabled": configuration.enabled,
    }


def _chain_state(chain: Any) -> dict[str, Any]:
    """Return a safe, comparable chain state without retaining its definition."""
    definition = chain.definition if isinstance(chain.definition, dict) else {}
    encoded = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "chain_id": str(chain.pk),
        "project_id": str(chain.project_id) if chain.project_id else None,
        "name": chain.name,
        "version": chain.version,
        "status": chain.status,
        "definition_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "published_at": chain.published_at.isoformat() if getattr(chain, "published_at", None) else None,
    }


def _actor_audit_snapshot(actor: Any, target: Any) -> tuple[str, str, dict[str, Any]]:
    """Capture the authenticated actor identity and authorized object scope."""
    from apps.projects.permissions import is_platform_admin, project_role

    project = getattr(target, "project", None)
    if project is None and getattr(target, "chain_id", None):
        chain = getattr(target, "chain", None)
        project = getattr(chain, "project", None)
    profile = getattr(actor, "profile", None)
    platform_role = getattr(profile, "role", "") if profile else ""
    scoped_role = project_role(actor, project) if project is not None else ""
    actor_role = platform_role if is_platform_admin(actor) else scoped_role or platform_role or ""
    display_name = actor.get_full_name().strip() if hasattr(actor, "get_full_name") else ""
    display_name = display_name or (actor.get_username() if hasattr(actor, "get_username") else str(actor))
    scope = {
        "scope_type": "project" if project is not None else "global",
        "project_id": str(project.pk) if project is not None else None,
        "project_name": project.name if project is not None else "",
        "project_role": scoped_role or "",
        "platform_role": platform_role or "",
        "platform_admin": is_platform_admin(actor),
    }
    return display_name[:150], actor_role[:40], scope


def record_governance_change(
    *,
    actor: Any,
    action: str,
    chain: Any | None = None,
    configuration: Any | None = None,
    before_state: dict[str, Any] | None = None,
    reason: str = "",
    result: str = "success",
    details: dict[str, Any] | None = None,
) -> Any:
    """Persist a scoped audit event with immutable actor and result snapshots."""
    from apps.skills.models import SkillChainGovernanceAudit

    target = configuration or chain
    if target is None:
        raise ValueError("an audited Skill chain or configuration is required")
    after_state = _configuration_state(configuration) if configuration is not None else _chain_state(chain)
    if details:
        after_state["details"] = deepcopy(details)
    actor_display_name, actor_role, actor_scope = _actor_audit_snapshot(actor, target)
    return SkillChainGovernanceAudit.objects.create(
        chain=chain or getattr(configuration, "chain", None),
        configuration=configuration,
        object_id=target.pk,
        action=action,
        before_state=deepcopy(before_state or {}),
        after_state=after_state,
        actor=actor,
        actor_display_name=actor_display_name,
        actor_role=actor_role,
        actor_scope=actor_scope,
        result=result,
        reason=(reason or "")[:500],
    )


@transaction.atomic
def rollback_skill_chain_configuration(configuration: Any, *, actor: Any, reason: str = "") -> Any:
    """Restore the previous audited configuration state and retain a rollback audit."""
    from apps.skills.models import SkillChain, SkillChainConfiguration, SkillChainGovernanceAudit

    current = SkillChainConfiguration.objects.select_for_update().select_related("chain").get(pk=configuration.pk)
    history = list(
        SkillChainGovernanceAudit.objects.filter(configuration=current)
        .order_by("-created_at", "-id")[:2]
    )
    if len(history) < 2:
        raise SkillChainLifecycleError(
            "no_rollback_target",
            "暂无可回滚配置版本；需要先有更早的配置状态。",
        )
    before = _configuration_state(current)
    target = history[1].after_state
    try:
        chain = SkillChain.objects.get(pk=target["chain_id"])
    except (KeyError, SkillChain.DoesNotExist) as exc:
        raise SkillChainLifecycleError(
            "rollback_target_unavailable",
            "历史配置引用的蓝图版本已不可用。",
        ) from exc
    current.chain = chain
    current.layer = target["layer"]
    current.project_id = target.get("project_id")
    current.feature_key = target.get("feature_key", "")
    current.request_key = target.get("request_key", "")
    current.version_lock = target.get("version_lock", "")
    current.overrides = deepcopy(target.get("overrides", {}))
    current.enabled = bool(target.get("enabled", True))
    current.full_clean()
    current.configuration_snapshot = deepcopy(target.get("configuration_snapshot", {}))
    current.updated_at = timezone.now()
    current.save(
        update_fields=(
            "chain", "layer", "project", "feature_key", "request_key",
            "version_lock", "overrides", "enabled", "configuration_snapshot", "updated_at",
        ),
        preserve_snapshot=True,
    )
    record_governance_change(
        actor=actor,
        action="rollback",
        configuration=current,
        before_state=before,
        reason=reason or "恢复到上一条配置审计版本",
    )
    return current


class SkillChainLifecycleError(ValueError):
    """Represent a safe, user-facing lifecycle conflict."""

    def __init__(self, reason_code: str, detail: str, *, http_status: int = 409) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.http_status = http_status


def _chain_family(chain: Any) -> Any:
    """Return all immutable versions that share one name and scope."""
    from apps.skills.models import SkillChain

    return SkillChain.objects.filter(name=chain.name, project_id=chain.project_id)


def chain_has_rollback_target(chain: Any) -> bool:
    """Return whether an earlier published version is available for explicit rollback."""
    historical_states = (
        "published",
        "enabled",
        "paused",
        "archived",
        "disabled",
        "rolled_back",
    )
    return _chain_family(chain).filter(
        published_at__isnull=False,
        published_at__lt=chain.created_at,
        status__in=historical_states,
    ).exclude(pk=chain.pk).exists()


def _next_chain_version(chain: Any) -> str:
    """Generate a unique patch version for a fork or rollback-derived draft."""
    from apps.skills.models import SkillChain

    versions = list(_chain_family(chain).values_list("version", flat=True))
    parsed = [_version_parts(item) for item in versions]
    semantic = [item for item in parsed if item is not None]
    candidate = (
        f"{max(semantic)[0]}.{max(semantic)[1]}.{max(semantic)[2] + 1}"
        if semantic
        else "1.0.0"
    )
    major, minor, patch = _version_parts(candidate) or (1, 0, 0)
    while SkillChain.objects.filter(
        project_id=chain.project_id,
        name=chain.name,
        version=candidate,
    ).exists():
        patch += 1
        candidate = f"{major}.{minor}.{patch}"
    return candidate


@transaction.atomic
def create_skill_chain_draft(source: Any, *, actor: Any, reason: str = "") -> Any:
    """Fork a version into a new editable draft without changing the source."""
    from apps.skills.models import SkillChain

    locked_source = SkillChain.objects.select_for_update().get(pk=source.pk)
    version = _next_chain_version(locked_source)
    draft = SkillChain.objects.create(
        project_id=locked_source.project_id,
        name=locked_source.name,
        version=version,
        description=locked_source.description,
        schema_version=locked_source.schema_version,
        definition=deepcopy(locked_source.definition),
        legacy_skill_ids=deepcopy(locked_source.legacy_skill_ids),
        status=SkillChain.Status.DRAFT,
        created_by=actor,
    )
    record_governance_change(
        actor=actor,
        action="chain_create",
        chain=draft,
        reason=reason or "创建新的Skill链草稿版本",
        details={"source_version": locked_source.version, "source_chain_id": str(locked_source.pk)},
    )
    record_governance_change(
        actor=actor,
        action="chain_fork",
        chain=draft,
        before_state=_chain_state(locked_source),
        reason=reason or "从既有蓝图版本派生新草稿",
        details={"source_version": locked_source.version, "source_chain_id": str(locked_source.pk)},
    )
    return draft


@transaction.atomic
def verify_skill_chain(chain: Any, *, actor: Any, reason: str = "") -> tuple[Any, list[dict[str, str]]]:
    """Validate references and record either the successful or blocked decision."""
    from apps.skills.models import SkillChain

    current = SkillChain.objects.select_for_update().get(pk=chain.pk)
    if current.status not in {SkillChain.Status.DRAFT, SkillChain.Status.VERIFIED}:
        raise SkillChainLifecycleError(
            "invalid_lifecycle_state",
            "只有草稿版本可以校验；已发布版本不可修改。",
        )
    before = _chain_state(current)
    issues = validate_chain_skill_references(current.definition, project_id=current.project_id)
    if issues:
        if current.status == SkillChain.Status.VERIFIED:
            current.status = SkillChain.Status.DRAFT
            current.save(update_fields=("status", "updated_at"))
        record_governance_change(
            actor=actor,
            action="chain_verify",
            chain=current,
            before_state=before,
            reason=reason or "蓝图校验未通过",
            result="failed",
            details={"issue_codes": sorted({item.get("code", "unknown") for item in issues})},
        )
        return current, issues
    current.status = SkillChain.Status.VERIFIED
    current.save(update_fields=("status", "updated_at"))
    record_governance_change(
        actor=actor,
        action="chain_verify",
        chain=current,
        before_state=before,
        reason=reason or "蓝图契约及能力引用校验通过",
    )
    return current, []


@transaction.atomic
def publish_skill_chain(chain: Any, *, actor: Any, reason: str = "") -> tuple[Any, list[dict[str, str]]]:
    """Publish a verified immutable version after a fresh compatibility check."""
    from apps.skills.models import SkillChain

    current = SkillChain.objects.select_for_update().get(pk=chain.pk)
    if current.status != SkillChain.Status.VERIFIED:
        raise SkillChainLifecycleError(
            "invalid_lifecycle_state",
            "请先完成蓝图校验，再发布该版本。",
        )
    issues = validate_chain_skill_references(current.definition, project_id=current.project_id)
    if issues:
        record_governance_change(
            actor=actor,
            action="chain_publish",
            chain=current,
            before_state=_chain_state(current),
            reason=reason or "发布前复核发现能力引用已不兼容",
            result="failed",
            details={"issue_codes": sorted({item.get("code", "unknown") for item in issues})},
        )
        return current, issues
    before = _chain_state(current)
    current.status = SkillChain.Status.PUBLISHED
    current.published_at = timezone.now()
    current.save(update_fields=("status", "published_at", "updated_at"))
    record_governance_change(
        actor=actor,
        action="chain_publish",
        chain=current,
        before_state=before,
        reason=reason or "发布已校验的蓝图版本",
    )
    return current, []


@transaction.atomic
def enable_skill_chain(chain: Any, *, actor: Any, reason: str = "") -> tuple[Any, list[dict[str, str]]]:
    """Enable one published version and retire a previously enabled sibling."""
    from apps.skills.models import SkillChain

    current = SkillChain.objects.select_for_update().get(pk=chain.pk)
    if current.status == SkillChain.Status.ENABLED:
        return current, []
    allowed_states = {
        SkillChain.Status.PUBLISHED,
        SkillChain.Status.PAUSED,
        SkillChain.Status.DISABLED,
    }
    if current.status not in allowed_states:
        raise SkillChainLifecycleError(
            "invalid_lifecycle_state",
            "蓝图必须先完成校验和发布，才能启用。",
        )
    issues = validate_chain_skill_references(current.definition, project_id=current.project_id)
    if issues:
        return current, issues
    siblings = _chain_family(current).select_for_update().filter(status=SkillChain.Status.ENABLED).exclude(pk=current.pk)
    for sibling in siblings:
        before_sibling = _chain_state(sibling)
        sibling.status = SkillChain.Status.PUBLISHED
        sibling.save(update_fields=("status", "updated_at"))
        record_governance_change(
            actor=actor,
            action="chain_superseded",
            chain=sibling,
            before_state=before_sibling,
            reason="同一蓝图的新版本已启用",
            details={"replacement_version": current.version, "replacement_chain_id": str(current.pk)},
        )
    before = _chain_state(current)
    current.status = SkillChain.Status.ENABLED
    if current.published_at is None:
        current.published_at = timezone.now()
    current.save(update_fields=("status", "published_at", "updated_at"))
    record_governance_change(
        actor=actor,
        action="chain_enable",
        chain=current,
        before_state=before,
        reason=reason or "允许新运行选择该蓝图版本",
    )
    return current, []


@transaction.atomic
def pause_skill_chain(chain: Any, *, actor: Any, reason: str = "") -> Any:
    """Pause new run selection for a blueprint while leaving existing runs alone."""
    from apps.skills.models import SkillChain

    current = SkillChain.objects.select_for_update().get(pk=chain.pk)
    if current.status != SkillChain.Status.ENABLED:
        raise SkillChainLifecycleError("invalid_lifecycle_state", "只有已启用蓝图可以暂停。")
    before = _chain_state(current)
    current.status = SkillChain.Status.PAUSED
    current.save(update_fields=("status", "updated_at"))
    record_governance_change(
        actor=actor,
        action="chain_pause",
        chain=current,
        before_state=before,
        reason=reason or "暂停新运行选择该蓝图；已开始运行不受影响",
    )
    return current


@transaction.atomic
def archive_skill_chain(chain: Any, *, actor: Any, reason: str = "") -> Any:
    """Archive a non-enabled version without deleting its history."""
    from apps.skills.models import SkillChain

    current = SkillChain.objects.select_for_update().get(pk=chain.pk)
    if current.status == SkillChain.Status.ENABLED:
        raise SkillChainLifecycleError("blueprint_enabled", "请先暂停蓝图，再归档版本。")
    if current.status == SkillChain.Status.ARCHIVED:
        return current
    before = _chain_state(current)
    current.status = SkillChain.Status.ARCHIVED
    current.save(update_fields=("status", "updated_at"))
    record_governance_change(
        actor=actor,
        action="chain_archive",
        chain=current,
        before_state=before,
        reason=reason or "归档蓝图版本",
    )
    return current


@transaction.atomic
def rollback_skill_chain_version(
    chain: Any,
    *,
    target_version_id: Any,
    actor: Any,
    reason: str = "",
) -> Any:
    """Create a new draft from an explicitly selected earlier published version."""
    from apps.skills.models import SkillChain

    current = SkillChain.objects.select_for_update().get(pk=chain.pk)
    family = _chain_family(current)
    candidate_ids = family.filter(
        published_at__isnull=False,
        published_at__lt=current.created_at,
        status__in=(
            SkillChain.Status.PUBLISHED,
            SkillChain.Status.ENABLED,
            SkillChain.Status.PAUSED,
            SkillChain.Status.ARCHIVED,
            SkillChain.Status.DISABLED,
            SkillChain.Status.ROLLED_BACK,
        ),
    ).exclude(pk=current.pk)
    if not candidate_ids.exists():
        raise SkillChainLifecycleError(
            "no_rollback_target",
            "暂无可回滚版本；需要先有更早的已发布版本。",
        )
    try:
        target = candidate_ids.select_for_update().get(pk=target_version_id)
    except (SkillChain.DoesNotExist, ValueError, TypeError):
        raise SkillChainLifecycleError(
            "invalid_rollback_target",
            "所选版本不属于当前蓝图范围、不是已发布历史版本或已不可用。",
        ) from None
    before = _chain_state(current)
    version = _next_chain_version(current)
    draft = SkillChain.objects.create(
        project_id=target.project_id,
        name=target.name,
        version=version,
        description=target.description,
        schema_version=target.schema_version,
        definition=deepcopy(target.definition),
        legacy_skill_ids=deepcopy(target.legacy_skill_ids),
        status=SkillChain.Status.DRAFT,
        created_by=actor,
    )
    details = {
        "source_version": current.version,
        "source_chain_id": str(current.pk),
        "restored_version": target.version,
        "restored_chain_id": str(target.pk),
    }
    record_governance_change(
        actor=actor,
        action="chain_create",
        chain=draft,
        reason=reason or "从历史蓝图版本创建回滚草稿",
        details=details,
    )
    record_governance_change(
        actor=actor,
        action="chain_rollback",
        chain=draft,
        before_state=before,
        reason=reason or f"选择版本 {target.version} 的内容创建新版本 {draft.version}",
        details=details,
    )
    return draft


def get_chain_history(chain: Any) -> Any:
    """Return lifecycle events for every retained version in the same scope."""
    from apps.skills.models import SkillChainGovernanceAudit

    chain_ids = _chain_family(chain).values_list("pk", flat=True)
    return SkillChainGovernanceAudit.objects.filter(
        chain_id__in=chain_ids,
        configuration__isnull=True,
    ).select_related("actor")


def diff_skill_chain_versions(before: Any, after: Any) -> dict[str, Any]:
    """Summarize contract differences without returning raw schema or prompt values."""
    before_definition = before.definition if isinstance(before.definition, dict) else {}
    after_definition = after.definition if isinstance(after.definition, dict) else {}
    old_nodes = {
        str(node.get("node_id")): node
        for node in before_definition.get("nodes", [])
        if isinstance(node, dict) and node.get("node_id")
    }
    new_nodes = {
        str(node.get("node_id")): node
        for node in after_definition.get("nodes", [])
        if isinstance(node, dict) and node.get("node_id")
    }
    node_changes: list[dict[str, str]] = []
    for node_id in sorted(set(old_nodes) | set(new_nodes)):
        old_node = old_nodes.get(node_id)
        new_node = new_nodes.get(node_id)
        if old_node is None:
            state = "added"
        elif new_node is None:
            state = "removed"
        elif old_node != new_node:
            state = "modified"
        else:
            continue
        node_changes.append({"node_id": node_id, "change": state})
    changed_fields = sorted(
        key
        for key in set(before_definition) | set(after_definition)
        if key != "nodes" and before_definition.get(key) != after_definition.get(key)
    )
    return {
        "from_version": before.version,
        "to_version": after.version,
        "description_changed": before.description != after.description,
        "schema_version_changed": before.schema_version != after.schema_version,
        "definition_fields_changed": changed_fields,
        "node_changes": node_changes,
        "legacy_skill_ids_changed": before.legacy_skill_ids != after.legacy_skill_ids,
    }


def _version_parts(value: str) -> tuple[int, int, int] | None:
    """Parse a basic semantic version used by Skill compatibility checks."""
    match = re.fullmatch(r"[vV]?(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?", value or "")
    return tuple(int(item) for item in match.groups()) if match else None


def _range_matches(version_range: str, version: str) -> bool:
    """Evaluate exact, wildcard, caret, tilde and comparator Skill ranges."""
    if version_range == "*":
        return True
    actual = _version_parts(version)
    if actual is None:
        return version_range in {version, f"={version}", f"=={version}"}
    if version_range.startswith("^") or version_range.startswith("~"):
        operator = version_range[0]
        requested = _version_parts(version_range[1:])
        if requested is None or actual < requested:
            return False
        if operator == "^":
            upper = (requested[0] + 1, 0, 0) if requested[0] else (0, requested[1] + 1, 0)
        else:
            upper = (requested[0], requested[1] + 1, 0)
        return actual < upper
    if any(symbol in version_range for symbol in (">", "<", ",")):
        for part in version_range.split(","):
            match = re.fullmatch(r"(>=|<=|>|<|==|=)?(.+)", part.strip())
            expected = _version_parts(match.group(2)) if match else None
            if match is None or expected is None:
                return False
            operator = match.group(1) or "=="
            if operator in ("=", "==") and actual != expected:
                return False
            if operator == ">=" and actual < expected:
                return False
            if operator == ">" and actual <= expected:
                return False
            if operator == "<=" and actual > expected:
                return False
            if operator == "<" and actual >= expected:
                return False
        return True
    return version_range.lstrip("=") == version


def validate_chain_skill_references(definition: dict[str, Any], *, project_id: Any | None) -> list[dict[str, str]]:
    """Check referenced Skills exist, are enabled, in scope and version-compatible."""
    from apps.skills.models import Skill

    nodes = definition.get("nodes", []) if isinstance(definition, dict) else []
    valid_ids: list[UUID] = []
    malformed_ids: set[str] = set()
    for node in nodes:
        if node.get("node_type") != "skill":
            continue
        skill_id = str(node.get("skill_id") or "")
        try:
            valid_ids.append(UUID(skill_id))
        except (ValueError, TypeError, AttributeError):
            malformed_ids.add(skill_id)
    skills = {str(item.pk): item for item in Skill.objects.filter(pk__in=valid_ids).select_related("project")}
    issues: list[dict[str, str]] = []
    for node in nodes:
        if node.get("node_type") != "skill":
            continue
        skill_id = str(node.get("skill_id") or "")
        skill = None if skill_id in malformed_ids else skills.get(skill_id)
        node_name = node.get("node_id", skill_id)
        if skill is None:
            issues.append({"code": "skill_missing", "message": f"节点“{node_name}”引用的能力不存在。"})
            continue
        if skill.project_id and str(skill.project_id) != str(project_id or ""):
            issues.append({"code": "skill_scope_mismatch", "message": f"节点“{node_name}”引用的能力不属于当前项目。"})
        if skill.status != Skill.Status.ENABLED:
            issues.append({"code": "skill_disabled", "message": f"节点“{node_name}”引用的能力“{skill.name}”已停用。"})
        version_range = node.get("skill_version_range", "*")
        if not _range_matches(version_range, skill.version):
            issues.append({
                "code": "skill_version_incompatible",
                "message": f"能力“{skill.name}”当前版本 {skill.version} 不满足 {version_range}。",
            })
    return issues


def _blocked_result(code: str, message: str, *, layers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build a stable and explainable blocked preview result."""
    return {
        "status": "blocked",
        "blocked": True,
        "reason_code": code,
        "reason": message,
        "source_layer": None,
        "source_label": None,
        "chain": None,
        "definition": None,
        "merged_overrides": {},
        "layers": layers or [],
        "runtime_ready": False,
        "runtime_ready_reason": "当前任务尚无受控适配器和真实运行环境预检；预览不代表可执行。",
    }


def resolve_skill_chain_configuration(
    *,
    project_id: Any | None = None,
    feature_key: str = "",
    request_key: str = "",
    instant_chain_id: str = "",
) -> dict[str, Any]:
    """Resolve global, project, feature and immediate layers with explicit blockers.

    Multiple declarations at one scope, disabled declarations, unavailable chains,
    version-lock mismatches and incompatible referenced Skills stop resolution;
    none of these cases silently falls back to a lower layer.
    """
    from apps.skills.contracts import SkillChainContractError, validate_skill_chain_definition
    from apps.skills.models import Skill, SkillChain, SkillChainConfiguration

    project_value = str(project_id) if project_id else None
    groups: dict[str, list[Any]] = {layer: [] for layer in LAYER_PRECEDENCE}
    if request_key:
        groups["instant"] = list(
            SkillChainConfiguration.objects.filter(layer="instant", request_key=request_key)
            .filter(project_id__isnull=True) if project_id is None else
            SkillChainConfiguration.objects.filter(layer="instant", request_key=request_key)
            .filter(project_id__in=(project_id, None))
        )
    if project_id and feature_key:
        groups["feature"] = list(
            SkillChainConfiguration.objects.filter(layer="feature", project_id=project_id, feature_key=feature_key)
        )
    if project_id:
        groups["project"] = list(
            SkillChainConfiguration.objects.filter(layer="project", project_id=project_id)
        )
    groups["global"] = list(
        SkillChainConfiguration.objects.filter(layer="global", project_id__isnull=True, chain__project__isnull=True)
    )

    if instant_chain_id:
        try:
            chain = SkillChain.objects.get(pk=instant_chain_id)
        except (SkillChain.DoesNotExist, ValueError, DjangoValidationError):
            return _blocked_result("instant_chain_missing", "即时选择的 Skill 链不存在或不可见。")
        if chain.project_id and str(chain.project_id) != str(project_id or ""):
            return _blocked_result("instant_chain_scope_mismatch", "即时选择的 Skill 链不属于当前项目。")
        groups["instant"] = [SimpleNamespace(
            id=None,
            pk=None,
            chain=chain,
            layer="instant",
            enabled=True,
            version_lock=chain.version,
            overrides={},
            configuration_snapshot={},
            project_id=project_id,
            feature_key=feature_key,
            request_key=request_key,
        )]

    present = [(layer, groups[layer]) for layer in LAYER_PRECEDENCE if groups[layer]]
    if not present:
        return {
            **_blocked_result("configuration_missing", "当前范围没有可用的 Skill 链配置。"),
            "status": "unconfigured",
            "blocked": False,
        }

    matched: list[tuple[str, Any]] = []
    for layer, candidates in present:
        if len(candidates) > 1:
            labels = "、".join(sorted({item.chain.name for item in candidates}))
            return _blocked_result(
                "configuration_conflict",
                f"{LAYER_LABELS[layer]}存在多个配置（{labels}），请先保留唯一配置。",
                layers=[{"layer": name, "layer_label": LAYER_LABELS[name], "count": len(rows)} for name, rows in present],
            )
        configuration = candidates[0]
        matched.append((layer, configuration))
        if not configuration.enabled:
            return _blocked_result(
                "configuration_disabled",
                f"{LAYER_LABELS[layer]}配置已停用；为避免静默降级，未使用低优先级配置。",
            )
        snapshot = configuration.configuration_snapshot or {}
        snapshot_chain = snapshot.get("chain", {}) if isinstance(snapshot, dict) else {}
        locked = configuration.version_lock
        pinned_version = snapshot_chain.get("version", configuration.chain.version)
        if locked and locked != pinned_version:
            return _blocked_result(
                "version_lock_mismatch",
                f"{LAYER_LABELS[layer]}锁定版本 {locked} 与配置快照版本 {pinned_version} 不一致。",
            )

    selected_layer, selected = matched[-1]
    selected_chain = selected.chain
    if selected_chain.status != SkillChain.Status.ENABLED:
        return _blocked_result(
            "chain_not_enabled",
            f"Skill 链“{selected_chain.name}”状态为“{selected_chain.get_status_display()}”，需先启用。",
            layers=[{"layer": layer, "layer_label": LAYER_LABELS[layer], "configuration_id": str(item.pk) if getattr(item, "pk", None) else None, "chain_name": item.chain.name} for layer, item in matched],
        )

    selected_snapshot = selected.configuration_snapshot or {}
    selected_chain_snapshot = selected_snapshot.get("chain", {}) if isinstance(selected_snapshot, dict) else {}
    base_definition = deepcopy(selected_chain_snapshot.get("definition") or selected_chain.definition)
    overrides: dict[str, Any] = {}
    for _, configuration in matched:
        value = configuration.overrides if isinstance(configuration.overrides, dict) else {}
        overrides = merge_configuration_fields(overrides, value)
    effective = merge_configuration_fields(base_definition, overrides)
    try:
        effective = validate_skill_chain_definition(effective)
    except SkillChainContractError as exc:
        return _blocked_result(
            "merged_contract_invalid",
            f"合并后的链路契约无效：{exc}",
            layers=[{"layer": layer, "layer_label": LAYER_LABELS[layer], "configuration_id": str(item.pk) if getattr(item, "pk", None) else None, "chain_name": item.chain.name} for layer, item in matched],
        )
    reference_issues = validate_chain_skill_references(effective, project_id=project_id)
    if reference_issues:
        result = _blocked_result("skill_not_compatible", "；".join(issue["message"] for issue in reference_issues))
        result["issues"] = reference_issues
        return result

    return {
        "status": "resolved",
        "blocked": False,
        "reason_code": "",
        "reason": "配置解析成功；此结果是预览，不代表 Skill 真实运行就绪。",
        "source_layer": selected_layer,
        "source_label": LAYER_LABELS[selected_layer],
        "chain": {
            "id": str(selected_chain.pk),
            "name": selected_chain.name,
            "version": selected_chain_snapshot.get("version", selected_chain.version),
            "status": selected_chain.status,
        },
        "definition": effective,
        "merged_overrides": overrides,
        "layers": [
            {
                "layer": layer,
                "layer_label": LAYER_LABELS[layer],
                "configuration_id": str(item.pk) if getattr(item, "pk", None) else None,
                "chain_name": item.chain.name,
                "version_lock": item.version_lock,
                "enabled": item.enabled,
            }
            for layer, item in matched
        ],
        "runtime_ready": False,
        "runtime_ready_reason": "T169/T169A 尚未提供受控适配器和真实执行预检；配置预览不能标记为运行就绪。",
    }


def get_configuration_history(configuration: Any) -> list[Any]:
    """Return audited configuration states in reverse chronological order."""
    from apps.skills.models import SkillChainGovernanceAudit

    return list(
        SkillChainGovernanceAudit.objects.filter(configuration=configuration)
        .select_related("actor")
        .order_by("-created_at", "-id")
    )
