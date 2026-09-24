"""Persistent Skill-chain execution, control and lineage services for T169."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.projects.permissions import is_platform_admin, project_role
from apps.skills.models import Skill, SkillChain, SkillChainConfiguration, SkillChainNodeRun, SkillChainRun, SkillChainRunEvent
from apps.skills.runtime import SkillRuntimeError, execute_skill
from apps.skills.services import resolve_skill_chain_configuration


TERMINAL_RUN_STATES = {
    SkillChainRun.Status.COMPLETED,
    SkillChainRun.Status.FAILED,
    SkillChainRun.Status.TIMED_OUT,
    SkillChainRun.Status.CANCELLED,
}


class SkillChainExecutionError(Exception):
    """A safe error raised when a run cannot be created or controlled."""

    def __init__(self, code: str, message: str, http_status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass(frozen=True)
class StartResult:
    """Return a run and whether it was newly created."""

    run: SkillChainRun
    created: bool


def _safe_snapshot(value: Any) -> Any:
    """Copy JSON values and mask common credential-shaped keys."""
    if isinstance(value, Mapping):
        masked = {"password", "secret", "token", "api_key", "authorization", "access_token", "refresh_token"}
        return {str(key): ("[REDACTED]" if str(key).casefold() in masked else _safe_snapshot(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_snapshot(item) for item in value]
    return value


def _topological_nodes(definition: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return canonical nodes in dependency order while preserving definition order."""
    nodes = [dict(item) for item in definition.get("nodes", [])]
    by_id = {item["node_id"]: item for item in nodes}
    order: list[dict[str, Any]] = []
    remaining = {item["node_id"]: set(item.get("depends_on", [])) for item in nodes}
    while remaining:
        ready = [item["node_id"] for item in nodes if item["node_id"] in remaining and not remaining[item["node_id"]]]
        if not ready:
            raise SkillChainExecutionError("dependency_cycle", "链路节点依赖无法形成执行顺序。", 409)
        for node_id in ready:
            order.append(by_id[node_id])
            remaining.pop(node_id)
            for dependencies in remaining.values():
                dependencies.discard(node_id)
    return order


def _user_can_run(user: Any, project_id: Any | None) -> bool:
    """Allow authenticated users to run global chains and visible project chains."""
    if is_platform_admin(user) or project_id is None:
        return True
    from apps.projects.models import Project

    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return False
    return project_role(user, project) is not None


def _skill_snapshot(skill: Skill) -> dict[str, Any]:
    """Freeze only the persisted metadata required by the controlled runtime."""
    return {
        "id": str(skill.pk),
        "project_id": str(skill.project_id) if skill.project_id else None,
        "name": skill.name,
        "version": skill.version,
        "input_schema": deepcopy(skill.input_schema or {}),
        "output_schema": deepcopy(skill.output_schema or {}),
        "runtime_key": skill.runtime_key,
        "timeout_seconds": skill.timeout_seconds,
    }


def _execution_snapshot(chain: SkillChain, resolved: Mapping[str, Any], definition: Mapping[str, Any]) -> dict[str, Any]:
    """Build an immutable chain/configuration/Skill snapshot for one run."""
    skill_ids = [node.get("skill_id") for node in definition.get("nodes", []) if node.get("node_type") == "skill"]
    skills = list(Skill.objects.filter(pk__in=[item for item in skill_ids if item]))
    by_id = {str(skill.pk): skill for skill in skills}
    missing = [item for item in skill_ids if item not in by_id]
    if missing:
        raise SkillChainExecutionError("skill_snapshot_missing", "运行启动时发现能力引用不可用，未创建运行。", 409)
    return {
        "snapshot_schema_version": "skill-chain-execution-v1",
        "chain": {
            "id": str(chain.pk),
            "name": chain.name,
            "version": chain.version,
            "schema_version": chain.schema_version,
            "status_at_start": chain.status,
        },
        "configuration": {
            "source_layer": resolved.get("source_layer", "instant"),
            "layers": deepcopy(resolved.get("layers", [])),
            "merged_overrides": deepcopy(resolved.get("merged_overrides", {})),
        },
        "definition": deepcopy(definition),
        "skills": [_skill_snapshot(by_id[item]) for item in skill_ids],
    }


def _record_event(run: SkillChainRun, event_type: str, *, node: SkillChainNodeRun | None = None, to_status: str = "", payload: Mapping[str, Any] | None = None) -> SkillChainRunEvent:
    """Append one ordered, redacted lineage event."""
    sequence = int(run.events.aggregate(value=Max("sequence")).get("value") or 0) + 1
    return SkillChainRunEvent.objects.create(
        run=run,
        node=node,
        sequence=sequence,
        event_type=event_type,
        from_status=run.status,
        to_status=to_status,
        node_key=node.node_id if node else "",
        payload=_safe_snapshot(dict(payload or {})),
    )


def _enqueue(run_id: str) -> None:
    """Queue execution after the creating transaction commits."""
    if settings.CELERY_TASK_ALWAYS_EAGER:
        SkillChainExecutionService().run(run_id)
        return
    from apps.skills.tasks import run_skill_chain

    run_skill_chain.delay(str(run_id))


def _schedule(run_id: str) -> None:
    """Run eagerly after persistence or enqueue after the surrounding commit."""
    if settings.CELERY_TASK_ALWAYS_EAGER:
        _enqueue(run_id)
    else:
        transaction.on_commit(lambda run_id=run_id: _enqueue(run_id))


class SkillChainExecutionService:
    """Create, execute, pause, resume, cancel and retry persisted runs."""

    def start(self, *, user: Any, payload: Mapping[str, Any]) -> StartResult:
        """Resolve a chain, freeze snapshots, persist nodes and enqueue execution."""
        if not isinstance(payload, Mapping):
            raise SkillChainExecutionError("invalid_input", "运行请求必须是 JSON 对象。", 400)
        key = str(payload.get("idempotency_key", "")).strip()[:128] or None
        if key:
            existing = SkillChainRun.objects.filter(requested_by=user, idempotency_key=key).first()
            if existing:
                return StartResult(existing, False)
        chain_id = str(payload.get("chain_id", "")).strip()
        project_id = payload.get("project_id") or None
        feature_key = str(payload.get("feature_key", "")).strip()
        request_key = str(payload.get("request_key", "")).strip()
        if chain_id:
            try:
                selected_chain = SkillChain.objects.get(pk=chain_id)
            except (SkillChain.DoesNotExist, ValueError):
                raise SkillChainExecutionError("chain_missing", "所选 Skill 链不存在或无权访问。", 404)
            project_id = project_id or selected_chain.project_id
        resolved = resolve_skill_chain_configuration(
            project_id=project_id,
            feature_key=feature_key,
            request_key=request_key,
            instant_chain_id=chain_id,
        )
        if resolved.get("blocked") or resolved.get("status") != "resolved":
            raise SkillChainExecutionError(
                str(resolved.get("reason_code") or "configuration_missing"),
                str(resolved.get("reason") or "当前范围没有可执行的 Skill 链配置。"),
                409,
            )
        selected_chain = SkillChain.objects.get(pk=resolved["chain"]["id"])
        if not _user_can_run(user, selected_chain.project_id):
            raise SkillChainExecutionError("run_forbidden", "当前账号没有该项目运行权限。", 403)
        definition = resolved.get("definition") or {}
        snapshot = _execution_snapshot(selected_chain, resolved, definition)
        input_snapshot = _safe_snapshot(payload.get("input", {}))
        ordered_nodes = _topological_nodes(definition)
        configuration_id = next((item.get("configuration_id") for item in reversed(resolved.get("layers", [])) if item.get("configuration_id")), None)
        configuration = SkillChainConfiguration.objects.filter(pk=configuration_id).first() if configuration_id else None
        with transaction.atomic():
            run = SkillChainRun.objects.create(
                chain=selected_chain,
                configuration=configuration,
                project_id=selected_chain.project_id or project_id,
                requested_by=user,
                idempotency_key=key,
                input_snapshot=input_snapshot,
                execution_snapshot=snapshot,
            )
            for position, node in enumerate(ordered_nodes):
                SkillChainNodeRun.objects.create(
                    run=run,
                    node_id=node["node_id"],
                    position=position,
                    node_type=node["node_type"],
                    definition_snapshot=_safe_snapshot(node),
                    max_retries=node.get("max_retries", 0),
                )
            _record_event(run, "run_created", to_status=run.status, payload={"node_count": len(ordered_nodes), "idempotent": bool(key)})
        _schedule(str(run.pk))
        run.refresh_from_db()
        return StartResult(run, True)

    def run(self, run_id: str) -> SkillChainRun:
        """Execute pending nodes cooperatively and persist every checkpoint."""
        run = SkillChainRun.objects.get(pk=run_id)
        if run.status in TERMINAL_RUN_STATES:
            return run
        if run.control_request == "cancel":
            return self._finish(run, SkillChainRun.Status.CANCELLED, "cancelled", "运行已取消。")
        if run.control_request == "pause":
            run.status = SkillChainRun.Status.PAUSED
            run.control_request = ""
            run.save(update_fields=("status", "control_request", "updated_at"))
            _record_event(run, "pause_confirmed", to_status=run.status)
            return run
        if run.started_at is None:
            run.started_at = timezone.now()
        run.status = SkillChainRun.Status.RUNNING
        run.save(update_fields=("status", "started_at", "updated_at"))
        _record_event(run, "run_started", to_status=run.status)
        snapshot = run.execution_snapshot
        definition = snapshot.get("definition", {}) if isinstance(snapshot, dict) else {}
        skill_by_id = {item.get("id"): item for item in snapshot.get("skills", []) if isinstance(item, dict)}
        node_runs = {item.node_id: item for item in run.nodes.all()}
        ordered_nodes = _topological_nodes(definition)
        outputs: dict[str, Any] = {node_id: node.output_snapshot for node_id, node in node_runs.items() if node.status == "completed"}
        for node in ordered_nodes:
            node_run = node_runs[node["node_id"]]
            if node_run.status == "completed":
                continue
            run.refresh_from_db()
            if run.control_request == "cancel":
                return self._finish(run, SkillChainRun.Status.CANCELLED, "cancelled", "运行已取消。")
            if run.control_request == "pause":
                run.status = SkillChainRun.Status.PAUSED
                run.control_request = ""
                run.checkpoint_node_id = run.checkpoint_node_id or ""
                run.save(update_fields=("status", "control_request", "updated_at"))
                _record_event(run, "pause_confirmed", to_status=run.status, payload={"checkpoint_node_id": run.checkpoint_node_id})
                return run
            if run.started_at and (timezone.now() - run.started_at).total_seconds() > int(definition.get("max_runtime_seconds", 300)):
                return self._finish(run, SkillChainRun.Status.TIMED_OUT, "run_timeout", "链路超过最大运行时长。")
            if node.get("node_type") == "human_gate":
                run.status = SkillChainRun.Status.WAITING_HUMAN
                run.current_node_id = node_run.node_id
                run.save(update_fields=("status", "current_node_id", "updated_at"))
                _record_event(run, "human_gate_waiting", node=node_run, to_status=run.status)
                return run
            upstream = {dependency: outputs.get(dependency, {}) for dependency in node.get("depends_on", [])}
            node_input = run.input_snapshot if not upstream else {"input": run.input_snapshot, "upstream": upstream}
            node_run.input_snapshot = _safe_snapshot(node_input)
            node_run.status = "running"
            node_run.started_at = timezone.now()
            node_run.attempt += 1
            node_run.error_code = ""
            node_run.error_message = ""
            node_run.save(update_fields=("status", "started_at", "attempt", "error_code", "error_message", "input_snapshot", "updated_at"))
            run.current_node_id = node_run.node_id
            run.save(update_fields=("current_node_id", "updated_at"))
            _record_event(run, "node_started", node=node_run, to_status=run.status, payload={"depends_on": node.get("depends_on", [])})
            skill_data = skill_by_id.get(node.get("skill_id"))
            if not skill_data:
                return self._fail_node(run, node_run, "skill_snapshot_missing", "节点引用的能力快照不存在。")
            try:
                result = execute_skill(
                    Skill(
                        id=skill_data["id"], name=skill_data["name"], version=skill_data["version"],
                        input_schema=skill_data.get("input_schema", {}), output_schema=skill_data.get("output_schema", {}),
                        runtime_key=skill_data.get("runtime_key", "configured"), timeout_seconds=skill_data.get("timeout_seconds", 30),
                        status=Skill.Status.ENABLED,
                    ),
                    node_input,
                    timeout=node.get("timeout_seconds"),
                )
            except SkillRuntimeError as exc:
                is_timeout = "timed out" in str(exc).casefold() or "timeout" in str(exc).casefold()
                if node_run.attempt <= node_run.max_retries and node.get("failure_strategy") == "retry":
                    node_run.status = "retrying"
                    node_run.error_code = "node_timeout" if is_timeout else "node_failed"
                    node_run.error_message = str(exc)[:500]
                    node_run.save(update_fields=("status", "error_code", "error_message", "updated_at"))
                    _record_event(run, "node_retry_scheduled", node=node_run, payload={"attempt": node_run.attempt})
                    continue
                return self._fail_node(run, node_run, "node_timeout" if is_timeout else "node_failed", str(exc))
            node_run.status = "completed"
            node_run.output_snapshot = _safe_snapshot(result)
            node_run.checkpoint_safe = True
            node_run.finished_at = timezone.now()
            node_run.save(update_fields=("status", "output_snapshot", "checkpoint_safe", "finished_at", "updated_at"))
            outputs[node_run.node_id] = node_run.output_snapshot
            run.checkpoint_node_id = node_run.node_id
            run.current_node_id = ""
            run.save(update_fields=("checkpoint_node_id", "current_node_id", "updated_at"))
            _record_event(run, "node_checkpoint", node=node_run, to_status=run.status, payload={"output_keys": sorted(result) if isinstance(result, dict) else []})
        run.output_snapshot = _safe_snapshot(outputs.get(ordered_nodes[-1]["node_id"], {}) if ordered_nodes else run.input_snapshot)
        run.current_node_id = ""
        run.status = SkillChainRun.Status.COMPLETED
        run.finished_at = timezone.now()
        run.control_request = ""
        run.save(update_fields=("status", "output_snapshot", "current_node_id", "finished_at", "control_request", "updated_at"))
        _record_event(run, "run_completed", to_status=run.status, payload={"checkpoint_node_id": run.checkpoint_node_id})
        return run

    def pause(self, run: SkillChainRun) -> SkillChainRun:
        """Request a pause and confirm immediately only before worker execution."""
        self._ensure_active(run)
        run.control_request = "pause"
        if run.status == SkillChainRun.Status.PENDING:
            run.status = SkillChainRun.Status.PAUSED
            run.control_request = ""
        elif run.status == SkillChainRun.Status.RUNNING:
            run.status = SkillChainRun.Status.PAUSE_REQUESTED
        run.save(update_fields=("status", "control_request", "updated_at"))
        _record_event(run, "pause_requested", to_status=run.status)
        return run

    def resume(self, run: SkillChainRun, *, input_value: Mapping[str, Any] | None = None) -> SkillChainRun:
        """Resume from the persisted checkpoint or complete a human gate input."""
        if run.status not in {SkillChainRun.Status.PAUSED, SkillChainRun.Status.WAITING_HUMAN}:
            raise SkillChainExecutionError("invalid_resume_state", "只有已暂停或等待人工的运行可以恢复。", 409)
        if run.status == SkillChainRun.Status.WAITING_HUMAN:
            node = run.nodes.filter(node_id=run.current_node_id).first()
            if node is None:
                raise SkillChainExecutionError("human_gate_missing", "等待人工节点不存在，无法恢复。", 409)
            node.status = "completed"
            node.output_snapshot = _safe_snapshot(dict(input_value or {}))
            node.checkpoint_safe = True
            node.finished_at = timezone.now()
            node.save(update_fields=("status", "output_snapshot", "checkpoint_safe", "finished_at", "updated_at"))
            run.checkpoint_node_id = node.node_id
        run.status = SkillChainRun.Status.PENDING
        run.control_request = ""
        run.error_code = ""
        run.error_message = ""
        run.save(update_fields=("status", "control_request", "error_code", "error_message", "checkpoint_node_id", "updated_at"))
        _record_event(run, "run_resumed", to_status=run.status, payload={"checkpoint_node_id": run.checkpoint_node_id})
        _schedule(str(run.pk))
        run.refresh_from_db()
        return run

    def cancel(self, run: SkillChainRun) -> SkillChainRun:
        """Request cancellation and persist a terminal result before worker start."""
        self._ensure_active(run)
        run.control_request = "cancel"
        if run.status in {
            SkillChainRun.Status.PENDING,
            SkillChainRun.Status.PAUSED,
            SkillChainRun.Status.PAUSE_REQUESTED,
            SkillChainRun.Status.WAITING_HUMAN,
            SkillChainRun.Status.CANCEL_REQUESTED,
        }:
            run.status = SkillChainRun.Status.CANCELLED
            run.control_request = ""
            run.finished_at = timezone.now()
        else:
            run.status = SkillChainRun.Status.CANCEL_REQUESTED
        run.save(update_fields=("status", "control_request", "finished_at", "updated_at"))
        _record_event(run, "cancel_requested", to_status=run.status)
        return run

    def retry_node(self, run: SkillChainRun, node_id: str) -> SkillChainRun:
        """Reset one failed node and enqueue the same immutable run snapshot."""
        if run.status not in {SkillChainRun.Status.FAILED, SkillChainRun.Status.TIMED_OUT}:
            raise SkillChainExecutionError("invalid_retry_state", "只有失败或超时的运行可以重试节点。", 409)
        node = run.nodes.filter(node_id=node_id).first()
        if node is None:
            raise SkillChainExecutionError("node_missing", "指定节点不存在。", 404)
        node.status = "pending"
        node.attempt = 0
        node.error_code = ""
        node.error_message = ""
        node.finished_at = None
        node.save(update_fields=("status", "attempt", "error_code", "error_message", "finished_at", "updated_at"))
        run.status = SkillChainRun.Status.PENDING
        run.error_code = ""
        run.error_message = ""
        run.finished_at = None
        run.control_request = ""
        run.save(update_fields=("status", "error_code", "error_message", "finished_at", "control_request", "updated_at"))
        _record_event(run, "node_retry_requested", node=node, to_status=run.status)
        _schedule(str(run.pk))
        run.refresh_from_db()
        return run

    @staticmethod
    def _ensure_active(run: SkillChainRun) -> None:
        """Reject controls for terminal runs."""
        if run.status in TERMINAL_RUN_STATES:
            raise SkillChainExecutionError("run_terminal", "运行已经结束，不能再控制。", 409)

    @staticmethod
    def _fail_node(run: SkillChainRun, node: SkillChainNodeRun, code: str, message: str) -> SkillChainRun:
        """Persist one node failure and its parent failure atomically."""
        node.status = "failed"
        node.error_code = code
        node.error_message = message[:500]
        node.finished_at = timezone.now()
        node.save(update_fields=("status", "error_code", "error_message", "finished_at", "updated_at"))
        run.status = SkillChainRun.Status.TIMED_OUT if code == "node_timeout" else SkillChainRun.Status.FAILED
        run.error_code = code
        run.error_message = message[:500]
        run.current_node_id = node.node_id
        run.finished_at = timezone.now()
        run.save(update_fields=("status", "error_code", "error_message", "current_node_id", "finished_at", "updated_at"))
        _record_event(run, "node_failed", node=node, to_status=run.status, payload={"error_code": code})
        return run

    @staticmethod
    def _finish(run: SkillChainRun, status: str, code: str, message: str) -> SkillChainRun:
        """Persist a terminal parent status with a safe reason."""
        run.status = status
        run.error_code = code
        run.error_message = message
        run.finished_at = timezone.now()
        run.current_node_id = ""
        run.control_request = ""
        run.save(update_fields=("status", "error_code", "error_message", "finished_at", "current_node_id", "control_request", "updated_at"))
        _record_event(run, "run_finished", to_status=run.status, payload={"error_code": code})
        return run


__all__ = ["SkillChainExecutionError", "SkillChainExecutionService", "StartResult"]
