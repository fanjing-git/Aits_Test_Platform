"""Business-facing parent runs backed by the real domain services."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from apps.skills.execution import _record_event, _safe_snapshot
from apps.skills.models import SkillChainNodeRun, SkillChainRun


class BusinessSkillRunError(ValueError):
    """Raised when a business operation cannot be attached to a parent run."""


class BusinessSkillRunService:
    """Create and finish parent runs around real business Service calls.

    The service deliberately does not call a Skill planning stub. Callers execute
    the existing requirement or case-generation Service and report its durable
    artifact back here, so a successful parent run always has a persisted result.
    """

    SNAPSHOT_VERSION = "business-skill-run-v1"

    def start(
        self,
        *,
        user: Any,
        project_id: Any,
        workflow_key: str,
        operation: str,
        business_type: str,
        business_id: Any,
        input_snapshot: Mapping[str, Any],
        node_id: str,
        skill_name: str,
        skill_version: str = "1.0.0",
    ) -> SkillChainRun:
        """Persist one business parent run and its real-service node."""
        workflow_key = str(workflow_key).strip()
        operation = str(operation).strip()
        node_id = str(node_id).strip()
        if not workflow_key or not operation or not node_id:
            raise BusinessSkillRunError("业务运行缺少工作流、操作或节点标识。")
        if not business_id:
            raise BusinessSkillRunError("业务运行缺少关联业务记录。")
        snapshot = {
            "snapshot_schema_version": self.SNAPSHOT_VERSION,
            "runtime_kind": "business_service",
            "workflow_key": workflow_key,
            "operation": operation,
            "business_ref": {"type": business_type, "id": str(business_id)},
            "service": {"name": skill_name, "version": skill_version},
            "definition": {
                "schema_version": "business-node-v1",
                "nodes": [{
                    "node_id": node_id,
                    "node_type": "business_service",
                    "operation": operation,
                    "skill_name": skill_name,
                    "skill_version": skill_version,
                    "depends_on": [],
                }],
            },
        }
        with transaction.atomic():
            run = SkillChainRun.objects.create(
                project_id=project_id,
                requested_by=user,
                input_snapshot=_safe_snapshot(dict(input_snapshot)),
                execution_snapshot=_safe_snapshot(snapshot),
            )
            node = SkillChainNodeRun.objects.create(
                run=run,
                node_id=node_id,
                position=0,
                node_type="business_service",
                definition_snapshot=_safe_snapshot(snapshot["definition"]["nodes"][0]),
            )
            _record_event(
                run,
                "business_run_created",
                node=node,
                to_status=run.status,
                payload={"workflow_key": workflow_key, "operation": operation},
            )
        return run

    def mark_running(self, run: SkillChainRun, node_id: str) -> SkillChainRun:
        """Mark the real business node as running."""
        node = self._node(run, node_id)
        node.status = "running"
        node.attempt += 1
        node.started_at = timezone.now()
        node.save(update_fields=("status", "attempt", "started_at", "updated_at"))
        run.status = SkillChainRun.Status.RUNNING
        run.current_node_id = node.node_id
        if run.started_at is None:
            run.started_at = timezone.now()
        run.save(update_fields=("status", "current_node_id", "started_at", "updated_at"))
        _record_event(run, "business_node_started", node=node, to_status=run.status)
        return run

    def complete(
        self,
        run: SkillChainRun,
        node_id: str,
        output_snapshot: Mapping[str, Any],
        *,
        artifact_ref: Mapping[str, Any],
    ) -> SkillChainRun:
        """Mark the node and parent complete only after artifact persistence."""
        node = self._node(run, node_id)
        node.status = "completed"
        node.output_snapshot = _safe_snapshot(dict(output_snapshot))
        node.checkpoint_safe = True
        node.finished_at = timezone.now()
        node.save(update_fields=("status", "output_snapshot", "checkpoint_safe", "finished_at", "updated_at"))
        run.status = SkillChainRun.Status.COMPLETED
        run.current_node_id = ""
        run.checkpoint_node_id = node.node_id
        run.output_snapshot = _safe_snapshot({"artifact": dict(artifact_ref), "result": dict(output_snapshot)})
        run.finished_at = timezone.now()
        run.save(update_fields=("status", "current_node_id", "checkpoint_node_id", "output_snapshot", "finished_at", "updated_at"))
        _record_event(run, "business_artifact_persisted", node=node, to_status=run.status, payload={"artifact": dict(artifact_ref)})
        _record_event(run, "run_completed", to_status=run.status, payload={"business_operation": run.execution_snapshot.get("operation", "")})
        return run

    def fail(self, run: SkillChainRun, node_id: str, code: str, message: str) -> SkillChainRun:
        """Persist a business-service failure without claiming an artifact."""
        node = self._node(run, node_id)
        node.status = "failed"
        node.error_code = str(code)[:60]
        node.error_message = str(message)[:500]
        node.finished_at = timezone.now()
        node.save(update_fields=("status", "error_code", "error_message", "finished_at", "updated_at"))
        run.status = SkillChainRun.Status.FAILED
        run.error_code = str(code)[:60]
        run.error_message = str(message)[:1000]
        run.current_node_id = ""
        run.finished_at = timezone.now()
        run.save(update_fields=("status", "error_code", "error_message", "current_node_id", "finished_at", "updated_at"))
        _record_event(run, "business_node_failed", node=node, to_status=run.status, payload={"error_code": code})
        return run

    @staticmethod
    def cancel_requested(run_id: Any) -> bool:
        """Return whether the parent run has received a cancellation request."""
        run = SkillChainRun.objects.filter(pk=run_id).only("control_request", "status").first()
        return bool(run and (run.control_request == "cancel" or run.status == SkillChainRun.Status.CANCEL_REQUESTED))

    @staticmethod
    def _node(run: SkillChainRun, node_id: str) -> SkillChainNodeRun:
        """Load the single business node or raise a safe contract error."""
        node = run.nodes.filter(node_id=node_id).first()
        if node is None:
            raise BusinessSkillRunError("业务运行节点不存在。")
        return node


def business_skill_execution(run: SkillChainRun, skill_name: str) -> dict[str, Any]:
    """Return the backwards-compatible UI summary for a real parent run."""
    return {
        "skill": skill_name,
        "version": str((run.execution_snapshot or {}).get("service", {}).get("version", "1.0.0")),
        "status": run.status,
        "runtime": "business_service",
        "run_id": str(run.pk),
        "message": "结果已写入业务记录" if run.status == SkillChainRun.Status.COMPLETED else "业务运行已持久化",
    }


__all__ = ["BusinessSkillRunError", "BusinessSkillRunService", "business_skill_execution"]
