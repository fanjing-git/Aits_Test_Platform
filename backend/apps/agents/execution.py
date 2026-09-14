"""Controlled model execution for project-scoped agent configurations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.agents.graph import build_agent_graph
from apps.agents.models import Agent, AgentExecution
from apps.agents.state import AgentState, new_agent_state
from apps.configs.models import ModelRoutingPolicy
from apps.configs.services import ProviderError, parse_openai_json_response, structured_chat
from apps.knowledge.models import KnowledgeBase
from apps.knowledge.embedding_policy import EmbeddingPolicyError, EmbeddingPolicyService
from apps.knowledge.retrieval import retrieve
from apps.projects.models import ProjectMember
from apps.projects.permissions import is_platform_admin, project_role
from core.llm.manager import ModelFallbackExhausted, ModelManager, ModelManagerError


class AgentExecutionError(RuntimeError):
    """A sanitized execution failure with a stable API-facing code."""

    def __init__(self, message: str, code: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


SAFE_TOOLS = frozenset({"knowledge_search"})
MAX_RESULT_TEXT = 10_000
MAX_TRACE_EVENTS = 40


def _bounded_text(value: Any, limit: int = MAX_RESULT_TEXT) -> str:
    """Convert model text to a bounded string suitable for persistence."""
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _safe_route(route: Any) -> dict[str, Any]:
    """Keep only non-secret routing metadata in an execution record."""
    if not isinstance(route, Mapping):
        return {}
    return {
        "feature_key": _bounded_text(route.get("feature_key"), 80),
        "required_model_types": [str(item)[:40] for item in route.get("required_model_types", []) if isinstance(item, str)][:5],
        "effective_source": _bounded_text(route.get("effective_source"), 40),
        "available": bool(route.get("available")),
        "candidates": [
            {
                "name": _bounded_text(candidate.get("name"), 100),
                "provider": _bounded_text(candidate.get("provider"), 40),
                "model_name": _bounded_text(candidate.get("model_name"), 200),
                "model_type": _bounded_text(candidate.get("model_type"), 40),
                "source": _bounded_text(candidate.get("source"), 40),
                "is_fallback": bool(candidate.get("is_fallback")),
            }
            for candidate in route.get("candidates", [])
            if isinstance(candidate, Mapping)
        ][:5],
    }


def _safe_value(value: Any, depth: int = 0) -> Any:
    """Limit arbitrary model JSON before returning it to the browser."""
    if depth > 2:
        return None
    if isinstance(value, str):
        return _bounded_text(value, 4_000)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_safe_value(item, depth + 1) for item in value[:20]]
    if isinstance(value, Mapping):
        return {
            str(key)[:80]: _safe_value(item, depth + 1)
            for key, item in list(value.items())[:30]
            if isinstance(key, (str, int))
        }
    return str(value)[:4_000]


def _safe_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Expose a small, stable subset of the model result schema."""
    allowed = ("answer", "summary", "next_action", "citations", "warnings", "tool_calls", "tool_results")
    return {key: _safe_value(result[key]) for key in allowed if key in result}


class AgentExecutionService:
    """Run one agent through routing, graph, tool authorization, and audit persistence."""

    def __init__(self, model_manager: ModelManager | None = None) -> None:
        self.model_manager = model_manager or ModelManager(factory=lambda config: config)

    @staticmethod
    def _append_trace(execution: AgentExecution, stage: str, status: str, **extra: Any) -> None:
        """Append a bounded, secret-free audit event."""
        trace = execution.trace if isinstance(execution.trace, list) else []
        event = {"stage": stage[:40], "status": status[:30], "at": timezone.now().isoformat()}
        for key, value in extra.items():
            if key in {"message", "code", "tool", "model_route"}:
                event[key] = _safe_value(value)
        execution.trace = (trace + [event])[-MAX_TRACE_EVENTS:]

    @staticmethod
    def _allowed_tools(agent: Agent) -> set[str]:
        """Return the intersection of configured tools and the platform allowlist."""
        configured = agent.parameters.get("allowed_tools", []) if isinstance(agent.parameters, dict) else []
        if not isinstance(configured, list):
            return set()
        return {item for item in configured if isinstance(item, str) and item in SAFE_TOOLS}

    @staticmethod
    def _project_knowledge_ids(agent: Agent) -> list[str]:
        """Filter configured knowledge IDs to active bases in the agent project."""
        configured = agent.knowledge_base_ids if isinstance(agent.knowledge_base_ids, list) else []
        return [
            str(item)
            for item in KnowledgeBase.objects.filter(
                project_id=agent.project_id,
                pk__in=[item for item in configured if isinstance(item, str)],
                status=KnowledgeBase.Status.ACTIVE,
            ).values_list("pk", flat=True)
        ]

    def start(self, agent: Agent, user: Any, input_text: str, interrupt_signal: str = "") -> AgentExecution:
        """Create an execution record and dispatch the controlled task."""
        if agent.status != Agent.Status.ACTIVE:
            raise AgentExecutionError("Only active agents can execute.", "agent_not_active")
        if not isinstance(input_text, str) or not input_text.strip():
            raise AgentExecutionError("Execution input cannot be empty.", "invalid_input")
        if interrupt_signal not in {"", "pause", "cancel"}:
            raise AgentExecutionError("Invalid interrupt signal.", "invalid_interrupt_signal")
        status = AgentExecution.Status.PENDING
        if interrupt_signal == "pause":
            status = AgentExecution.Status.PAUSED
        elif interrupt_signal == "cancel":
            status = AgentExecution.Status.CANCELLED
        execution = AgentExecution.objects.create(
            agent=agent,
            project=agent.project,
            requested_by=user,
            agent_name=agent.name,
            agent_version=agent.version,
            input_text=input_text.strip(),
            status=status,
            interrupt_signal=interrupt_signal,
        )
        self._append_trace(execution, "preflight", "paused" if status == AgentExecution.Status.PAUSED else "cancelled" if status == AgentExecution.Status.CANCELLED else "accepted")
        execution.save(update_fields=("trace", "updated_at"))
        if status == AgentExecution.Status.PENDING:
            from apps.agents.tasks import run_agent_execution

            try:
                result = run_agent_execution.delay(str(execution.pk))
                execution.task_id = getattr(result, "id", "") or ""
                execution.save(update_fields=("task_id", "updated_at"))
            except Exception as exc:
                self._fail(execution, exc)
            execution.refresh_from_db()
        return execution

    def run(self, execution_id: str) -> AgentExecution:
        """Execute a pending record, preserving a safe terminal audit state."""
        with transaction.atomic():
            execution = AgentExecution.objects.select_for_update().select_related("agent", "project", "requested_by").get(pk=execution_id)
            if execution.status != AgentExecution.Status.PENDING:
                return execution
            if execution.interrupt_signal == AgentExecution.InterruptSignal.CANCEL:
                execution.status = AgentExecution.Status.CANCELLED
                self._append_trace(execution, "preflight", "cancelled")
                execution.finished_at = timezone.now()
                execution.save()
                return execution
            if execution.interrupt_signal == AgentExecution.InterruptSignal.PAUSE:
                execution.status = AgentExecution.Status.PAUSED
                self._append_trace(execution, "preflight", "paused")
                execution.save()
                return execution
            execution.status = AgentExecution.Status.RUNNING
            execution.phase = "graph"
            execution.started_at = timezone.now()
            self._append_trace(execution, "graph", "started")
            execution.save()

        try:
            agent = Agent.objects.select_related("project", "model_config", "prompt_config").get(pk=execution.agent_id)
            state = new_agent_state(execution.input_text, str(agent.project_id), str(execution.requested_by_id))
            state.update({
                "agent_execution": True,
                "agent_id": str(agent.pk),
                "agent_version": agent.version,
                "agent_skill_ids": list(agent.skill_ids or []),
                "agent_knowledge_base_ids": self._project_knowledge_ids(agent),
            })
            final_state = build_agent_graph().invoke(state, model_executor=lambda current: self._invoke_model(execution, agent, current))
            execution.refresh_from_db()
            if execution.status in {AgentExecution.Status.PAUSED, AgentExecution.Status.CANCELLED}:
                return execution
            if final_state.get("execution_status") == "failed":
                raise AgentExecutionError(str(final_state.get("error_message") or "Agent graph execution failed."), "graph_failed", retryable=True)
            execution.status = AgentExecution.Status.COMPLETED
            execution.phase = "completed"
            execution.result = _safe_result(final_state.get("model_result", {}))
            self._append_trace(execution, "graph", "completed")
            execution.finished_at = timezone.now()
            execution.save()
        except Exception as exc:
            execution.refresh_from_db()
            if execution.status not in {AgentExecution.Status.PAUSED, AgentExecution.Status.CANCELLED}:
                self._fail(execution, exc)
        return execution

    def _invoke_model(self, execution: AgentExecution, agent: Agent, state: AgentState) -> AgentState:
        """Resolve the configured route, call structured output, and authorize tools."""
        route = self.model_manager.resolve_route(
            ModelRoutingPolicy.FeatureKey.AGENT_EXECUTION,
            task_type="agent_execution",
            preferred_name=agent.model_config.name,
        )
        execution.model_route = _safe_route(route.as_dict())
        execution.phase = "model_call"
        self._append_trace(execution, "model_route", "resolved", model_route=execution.model_route)
        execution.save(update_fields=("model_route", "phase", "trace", "updated_at"))
        system_prompt = agent.prompt_config.content if agent.prompt_config and agent.prompt_config.is_active else "You are a controlled agent in a software testing platform. Return a JSON object only."
        allowed_tools = sorted(self._allowed_tools(agent))
        system_prompt = (
            f"{system_prompt}\n\nAgent: {agent.name} v{agent.version}."
            f"\nAllowed tool whitelist: {json.dumps(allowed_tools)}."
            "\nRequest only whitelisted tools in a tool_calls array with name and arguments fields."
            "\nOutput must be a JSON object and may contain answer, summary, next_action, citations, warnings, and tool_calls."
        )
        parameters = agent.parameters if isinstance(agent.parameters, dict) else {}
        try:
            max_tokens = max(512, min(8192, int(parameters.get("max_tokens", 2048) or 2048)))
        except (TypeError, ValueError):
            max_tokens = 2048
        try:
            temperature = max(0.0, min(1.0, float(parameters.get("temperature", 0) or 0)))
        except (TypeError, ValueError):
            temperature = 0.0
        try:
            timeout = max(1, min(300, int(parameters.get("execution_timeout_seconds", 30) or 30)))
        except (TypeError, ValueError):
            timeout = 30
        response = self.model_manager.execute_routed(
            ModelRoutingPolicy.FeatureKey.AGENT_EXECUTION,
            lambda _runtime, config: parse_openai_json_response(structured_chat(
                config,
                messages=(
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": execution.input_text},
                ),
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )),
            task_type="agent_execution",
            preferred_name=agent.model_config.name,
            retry_on=(ProviderError, TimeoutError, OSError),
        )
        execution.refresh_from_db()
        if execution.status in {AgentExecution.Status.PAUSED, AgentExecution.Status.CANCELLED}:
            state["execution_status"] = execution.status
            state["route"] = "wait_for_input" if execution.status == AgentExecution.Status.PAUSED else "cancelled"
            return state
        result = _safe_result(response)
        tool_results = self._execute_tools(agent, result.get("tool_calls", []))
        if tool_results:
            result["tool_results"] = tool_results
        state["model_result"] = result
        state["execution_status"] = "completed"
        self._append_trace(execution, "model_call", "completed")
        if tool_results:
            self._append_trace(execution, "tool", "completed", tool="knowledge_search")
        execution.save(update_fields=("phase", "trace", "updated_at"))
        return state

    def _execute_tools(self, agent: Agent, tool_calls: Any) -> list[dict[str, Any]]:
        """Execute only explicitly configured, platform-approved tools."""
        if tool_calls is None:
            return []
        if not isinstance(tool_calls, list):
            raise AgentExecutionError("Model tool call list is invalid.", "invalid_tool_calls")
        if len(tool_calls) > 5:
            raise AgentExecutionError("Model tool call limit exceeded.", "tool_limit_exceeded")
        allowed_tools = self._allowed_tools(agent)
        results: list[dict[str, Any]] = []
        for call in tool_calls:
            if not isinstance(call, Mapping):
                raise AgentExecutionError("Model tool call is invalid.", "invalid_tool_call")
            name = call.get("name")
            if not isinstance(name, str) or name not in SAFE_TOOLS or name not in allowed_tools:
                raise AgentExecutionError("Model requested an unauthorized tool; execution was blocked.", "tool_not_authorized")
            arguments = call.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError as exc:
                    raise AgentExecutionError("Tool arguments are not valid JSON.", "invalid_tool_arguments") from exc
            if not isinstance(arguments, Mapping) or not isinstance(arguments.get("query"), str) or not arguments["query"].strip():
                raise AgentExecutionError("Knowledge search requires a query.", "invalid_tool_arguments")
            knowledge_base_ids = self._project_knowledge_ids(agent)
            if not knowledge_base_ids:
                raise AgentExecutionError(
                    "当前智能体未配置可检索的项目知识库。",
                    "knowledge_not_configured",
                )
            try:
                embedding_execution = EmbeddingPolicyService().prepare("provider")
            except EmbeddingPolicyError as exc:
                raise AgentExecutionError(str(exc), exc.code) from exc
            hits = retrieve(
                arguments["query"].strip(),
                knowledge_base_ids,
                vectorizer=embedding_execution.vectorizer,
                top_k=5,
            )
            results.append({
                "tool": name,
                "items": [
                    {"knowledge_base_id": hit.knowledge_base_id, "document_id": hit.document_id, "content": hit.content[:2_000], "score": hit.score}
                    for hit in hits
                ],
            })
        return results

    def request_interrupt(self, execution: AgentExecution, user: Any, signal: str) -> AgentExecution:
        """Pause or cancel a pending/running execution for an authorized user."""
        if not self.can_mutate(execution, user):
            raise PermissionError("You cannot control this agent execution.")
        if signal not in {"pause", "cancel"}:
            raise AgentExecutionError("Invalid interrupt signal.", "invalid_interrupt_signal")
        if execution.status in {AgentExecution.Status.COMPLETED, AgentExecution.Status.FAILED, AgentExecution.Status.CANCELLED}:
            raise AgentExecutionError("This execution has already finished.", "execution_already_finished")
        execution.interrupt_signal = signal
        execution.status = AgentExecution.Status.PAUSED if signal == "pause" else AgentExecution.Status.CANCELLED
        execution.phase = "paused" if signal == "pause" else "cancelled"
        execution.finished_at = timezone.now() if signal == "cancel" else None
        self._append_trace(execution, "control", signal)
        execution.save()
        return execution

    def resume(self, execution: AgentExecution, user: Any) -> AgentExecution:
        """Resume a paused execution through the same controlled task path."""
        if not self.can_mutate(execution, user):
            raise PermissionError("You cannot control this agent execution.")
        if execution.status != AgentExecution.Status.PAUSED:
            raise AgentExecutionError("Only a paused execution can be resumed.", "execution_not_paused")
        execution.status = AgentExecution.Status.PENDING
        execution.interrupt_signal = ""
        execution.phase = "queued"
        self._append_trace(execution, "control", "resumed")
        execution.save()
        from apps.agents.tasks import run_agent_execution

        try:
            run_agent_execution.delay(str(execution.pk))
        except Exception as exc:
            self._fail(execution, exc)
        execution.refresh_from_db()
        return execution

    @staticmethod
    def can_mutate(execution: AgentExecution, user: Any) -> bool:
        """Return whether a user may control an execution in its project."""
        if is_platform_admin(user):
            return True
        return execution.requested_by_id == getattr(user, "pk", None) or project_role(user, execution.project) in {
            ProjectMember.Role.OWNER,
            ProjectMember.Role.MANAGER,
        }

    def _fail(self, execution: AgentExecution, exc: Exception) -> None:
        """Persist a sanitized terminal failure without exposing provider secrets."""
        source = exc.last_error if isinstance(exc, ModelFallbackExhausted) else exc
        code = getattr(source, "code", "model_execution_failed")
        if isinstance(exc, AgentExecutionError):
            code = exc.code
        message = str(source) if isinstance(source, (AgentExecutionError, ProviderError)) else "Model execution failed. Check routing, network, and model configuration before retrying."
        retryable = bool(getattr(source, "retryable", False)) or code in {"timeout", "tcp_blocked", "provider_http_error", "quota_exhausted", "model_execution_failed"}
        execution.status = AgentExecution.Status.FAILED
        execution.phase = "failed"
        execution.error_code = str(code)[:80]
        execution.error_message = _bounded_text(message, 1_000)
        execution.retryable = retryable
        execution.finished_at = timezone.now()
        self._append_trace(execution, "execution", "failed", code=execution.error_code, message=execution.error_message)
        execution.save()
