"""HTTP API executor for immediate, script, and full test runs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

import requests

from apps.tests.executor.base import BaseExecutor, ExecutionResult, ExecutorConfigurationError
from apps.tests.models import TestCase, TestRun


class APIExecutor(BaseExecutor):
    """Execute structured API cases without exposing response or auth values."""

    ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

    def __init__(self, run: TestRun, *, session: requests.Session | Any | None = None, **kwargs: Any) -> None:
        """Create an API executor with an injectable HTTP session for safe tests."""
        super().__init__(run, **kwargs)
        self.session = session or requests.Session()
        self._owns_session = session is None

    def execute(self) -> ExecutionResult:
        """Dispatch the configured run mode to its bounded execution path."""
        try:
            self.ensure_environment_ready()
            mode = self.run.mode
            if mode == TestRun.Mode.SCRIPT:
                return self._execute_script()
            cases = list(self.run.test_cases.order_by("case_id"))
            if mode == TestRun.Mode.IMMEDIATE:
                if len(cases) != 1:
                    raise ExecutorConfigurationError("即时模式必须且只能选择一个测试用例。", "immediate_case_count")
                cases = cases[:1]
            elif mode != TestRun.Mode.FULL:
                raise ExecutorConfigurationError("不支持的接口测试执行模式。", "unsupported_execution_mode")
            pytest_path = self.run.execution_config.get("pytest_path") if isinstance(self.run.execution_config, dict) else None
            if mode == TestRun.Mode.FULL and pytest_path:
                return self.run_pytest(str(pytest_path))
            return self._execute_cases(cases)
        except ExecutorConfigurationError as exc:
            return ExecutionResult(
                status="error",
                exit_code=None,
                error_code=exc.code,
                error_message=exc.message,
                environment=self.environment_context(),
                workspace=str(self.workspace) if self.workspace else "",
            )
        finally:
            if self._owns_session:
                self.session.close()

    def _execute_cases(self, cases: Sequence[TestCase]) -> ExecutionResult:
        """Execute cases in stable order and aggregate their safe summaries."""
        if not cases:
            raise ExecutorConfigurationError("当前执行没有关联测试用例。", "empty_test_cases")
        details: list[dict[str, Any]] = []
        context: dict[str, Any] = {}
        started = monotonic()
        for case in cases:
            details.append(self._execute_case(case, context))
        passed = sum(item["status"] == "passed" for item in details)
        failed = sum(item["status"] == "failed" for item in details)
        skipped = sum(item["status"] == "skipped" for item in details)
        errors = sum(item["status"] == "error" for item in details)
        status = "error" if errors else "failed" if failed else "skipped" if skipped == len(details) else "passed"
        return ExecutionResult(
            status=status,
            exit_code=0 if status in {"passed", "skipped"} else 1,
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            duration_ms=max(0, round((monotonic() - started) * 1000)),
            details=details,
            environment=self.environment_context(),
            workspace=str(self.workspace) if self.workspace else "",
        )

    def _execute_case(self, case: TestCase, context: dict[str, Any]) -> dict[str, Any]:
        """Execute every structured step in one case and stop on the first failure."""
        if not isinstance(case.steps, list) or not case.steps:
            return self._case_error(case, "invalid_steps", "测试用例没有可执行步骤。")
        case_started = monotonic()
        assertions: list[dict[str, Any]] = []
        status_code: int | None = None
        response_summary: dict[str, Any] = {}
        for index, raw_step in enumerate(case.steps, start=1):
            if not isinstance(raw_step, Mapping):
                return self._case_error(case, "unsupported_step_format", f"第 {index} 步不是结构化接口请求。")
            try:
                response, response_summary = self._request_step(raw_step, context)
            except requests.Timeout:
                return self._case_error(case, "request_timeout", f"第 {index} 步请求超时。", case_started)
            except requests.ConnectionError:
                return self._case_error(case, "request_connection_error", f"第 {index} 步无法连接目标环境。", case_started)
            except requests.RequestException:
                return self._case_error(case, "request_error", f"第 {index} 步请求失败。", case_started)
            except ExecutorConfigurationError as exc:
                return self._case_error(case, exc.code, exc.message, case_started)
            status_code = response.status_code
            assertions = self._evaluate_assertions(raw_step, response, response_summary)
            if not all(item["passed"] for item in assertions):
                return self._case_result(
                    case,
                    "failed",
                    case_started,
                    status_code,
                    response_summary,
                    assertions,
                    "assertion_failed",
                    "接口断言未通过。",
                )
            self._extract_data_flow(case, index, response, context)
        return self._case_result(case, "passed", case_started, status_code, response_summary, assertions)

    def _request_step(
        self, step: Mapping[str, Any], context: Mapping[str, Any]
    ) -> tuple[requests.Response, dict[str, Any]]:
        """Build and send one request while constraining it to the selected environment."""
        method = str(step.get("method") or "GET").upper()
        if method not in self.ALLOWED_METHODS:
            raise ExecutorConfigurationError("请求方法不在允许范围内。", "invalid_http_method")
        raw_url = self._render(step.get("url") or step.get("path") or step.get("endpoint"), context)
        url = self._safe_url(raw_url)
        headers = self._request_headers(step.get("headers"), context)
        params = self._render_mapping(step.get("params"), context)
        body = step.get("json", step.get("body"))
        body = self._render(body, context) if body is not None else None
        response = self.session.request(
            method,
            url,
            headers=headers,
            params=params,
            json=body,
            timeout=self.timeout_seconds,
        )
        return response, self._response_summary(response)

    def _execute_script(self) -> ExecutionResult:
        """Run a project-provided script from the isolated workspace and parse JSON only."""
        config = self.run.execution_config if isinstance(self.run.execution_config, dict) else {}
        script_path = config.get("script_path")
        if not isinstance(script_path, str) or not script_path.strip():
            raise ExecutorConfigurationError("脚本模式必须配置 script_path。", "script_path_required")
        workspace = self._workspace or self.prepare_workspace()
        script = self.resolve_workspace_path(script_path)
        if not script.is_file():
            raise ExecutorConfigurationError("脚本文件不存在于执行工作目录。", "script_file_not_found")
        process_env = os.environ.copy()
        process_env["PYTHONDONTWRITEBYTECODE"] = "1"
        process_env["AITS_TEST_BASE_URL"] = self.environment_context().get("base_url", "")
        started = monotonic()
        try:
            completed = subprocess.run(
                [sys.executable, str(script.relative_to(workspace))],
                cwd=workspace,
                capture_output=True,
                check=False,
                encoding="utf-8",
                errors="replace",
                env=process_env,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                status="error", exit_code=None, duration_ms=self._duration_ms(started), timed_out=True,
                error_code="script_timeout", error_message="接口测试脚本执行超时。",
                environment=self.environment_context(), workspace=str(workspace),
            )
        except (OSError, subprocess.SubprocessError):
            return ExecutionResult(
                status="error", exit_code=None, duration_ms=self._duration_ms(started),
                error_code="script_process_error", error_message="接口测试脚本启动失败。",
                environment=self.environment_context(), workspace=str(workspace),
            )
        raw_stdout = completed.stdout
        stdout = self._redact_output(raw_stdout)
        stderr = self._redact_output(completed.stderr)
        if completed.returncode != 0:
            return ExecutionResult(
                status="error", exit_code=completed.returncode, duration_ms=self._duration_ms(started),
                stdout=stdout, stderr=stderr, error_code="script_nonzero_exit",
                error_message="接口测试脚本执行失败。", environment=self.environment_context(), workspace=str(workspace),
            )
        try:
            payload = json.loads(raw_stdout)
        except (TypeError, json.JSONDecodeError):
            return ExecutionResult(
                status="error", exit_code=completed.returncode, duration_ms=self._duration_ms(started),
                stdout=stdout, stderr=stderr, error_code="invalid_script_output",
                error_message="接口测试脚本必须输出 JSON 对象。", environment=self.environment_context(), workspace=str(workspace),
            )
        if not isinstance(payload, Mapping):
            return ExecutionResult(
                status="error", exit_code=completed.returncode, duration_ms=self._duration_ms(started),
                stdout=stdout, stderr=stderr, error_code="invalid_script_output",
                error_message="接口测试脚本输出必须是 JSON 对象。", environment=self.environment_context(), workspace=str(workspace),
            )
        status = str(payload.get("status") or "passed")
        if status not in {"passed", "failed", "skipped", "error"}:
            status = "error"
        return ExecutionResult(
            status=status,
            exit_code=completed.returncode,
            passed=self._count(payload.get("passed")),
            failed=self._count(payload.get("failed")),
            skipped=self._count(payload.get("skipped")),
            errors=self._count(payload.get("errors")),
            duration_ms=self._duration_ms(started),
            stdout=stdout,
            stderr=stderr,
            details=self._redact_json(payload.get("details")) if isinstance(payload.get("details"), list) else [],
            environment=self.environment_context(),
            workspace=str(workspace),
        )

    def _evaluate_assertions(
        self, step: Mapping[str, Any], response: requests.Response, summary: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        """Evaluate status and simple JSON presence assertions without storing values."""
        expected = step.get("expected_status", step.get("status_code"))
        assertions = [{"kind": "status_code", "passed": 200 <= response.status_code < 300}]
        if expected is not None:
            accepted = expected if isinstance(expected, list) else [expected]
            assertions[-1] = {"kind": "status_code", "expected": accepted, "passed": response.status_code in accepted}
        for item in step.get("assertions", []) if isinstance(step.get("assertions"), list) else []:
            if not isinstance(item, Mapping):
                assertions.append({"kind": "invalid", "passed": False})
                continue
            path = item.get("json_path") or item.get("field")
            if not isinstance(path, str) or not path.strip():
                assertions.append({"kind": "invalid", "passed": False})
                continue
            present = self._json_path_exists(summary.get("json_body"), path)
            assertions.append({"kind": "json_path", "path": path, "passed": present == item.get("exists", True)})
        return assertions

    def _extract_data_flow(self, case: TestCase, step_index: int, response: requests.Response, context: dict[str, Any]) -> None:
        """Extract configured response fields into memory for subsequent steps only."""
        flows = getattr(case, "data_flow", None)
        if not isinstance(flows, list) and isinstance(case.input_data, Mapping):
            flows = case.input_data.get("data_flow")
        if not isinstance(flows, list):
            return
        try:
            body = response.json()
        except ValueError:
            return
        for flow in flows:
            if not isinstance(flow, Mapping):
                continue
            source = flow.get("source") if isinstance(flow.get("source"), Mapping) else {}
            target = flow.get("target") if isinstance(flow.get("target"), Mapping) else {}
            if str(source.get("step_id")) and str(target.get("step_id")):
                value = self._json_path_value(body, str(source.get("field") or ""))
                if value is not None:
                    context[str(target.get("field"))] = value

    def _case_result(
        self, case: TestCase, status: str, started: float, status_code: int | None,
        response_summary: Mapping[str, Any], assertions: Sequence[Mapping[str, Any]],
        error_code: str = "", error_message: str = "",
    ) -> dict[str, Any]:
        """Create a safe per-case result summary."""
        return {
            "case_id": case.case_id,
            "status": status,
            "duration_ms": self._duration_ms(started),
            "status_code": status_code,
            "response_summary": {key: value for key, value in response_summary.items() if key != "json_body"},
            "assertions": [dict(item) for item in assertions],
            "error_code": error_code,
            "error_message": error_message,
        }

    def _case_error(self, case: TestCase, code: str, message: str, started: float | None = None) -> dict[str, Any]:
        """Create a safe error result without request payloads or response bodies."""
        return self._case_result(case, "error", started or monotonic(), None, {}, [], code, message)

    def _safe_url(self, value: Any) -> str:
        """Resolve a relative path and reject cross-origin or credentialed URLs."""
        if not isinstance(value, str) or not value.strip():
            raise ExecutorConfigurationError("接口步骤必须提供 path 或 url。", "request_url_required")
        base = str(self.environment_context()["base_url"]).rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc:
            candidate = value
            base_parts = urlsplit(base)
            candidate_parts = urlsplit(candidate)
            if candidate_parts.scheme not in {"http", "https"} or (candidate_parts.scheme, candidate_parts.netloc) != (base_parts.scheme, base_parts.netloc):
                raise ExecutorConfigurationError("接口地址必须属于当前测试环境。", "request_origin_mismatch")
            if candidate_parts.username or candidate_parts.password:
                raise ExecutorConfigurationError("接口地址不能包含认证信息。", "request_url_credentials")
            return candidate
        return f"{base}/{value.lstrip('/')}"

    def _request_headers(self, value: Any, context: Mapping[str, Any]) -> dict[str, str]:
        """Combine step headers with encrypted environment auth without returning values."""
        if value is not None and not isinstance(value, Mapping):
            raise ExecutorConfigurationError("请求 headers 必须是 JSON 对象。", "invalid_request_headers")
        headers = {str(key): str(self._render(item, context)) for key, item in (value or {}).items()}
        environment = self._load_environment()
        auth_config = environment.auth_config if environment is not None and isinstance(environment.auth_config, Mapping) else {}
        configured_headers = auth_config.get("headers") if isinstance(auth_config.get("headers"), Mapping) else {}
        for key, item in configured_headers.items():
            headers.setdefault(str(key), str(item))
        if "Authorization" not in headers:
            authorization = auth_config.get("authorization")
            token = auth_config.get("token")
            if authorization:
                headers["Authorization"] = str(authorization)
            elif token:
                headers["Authorization"] = f"Bearer {token}"
        return headers

    def _response_summary(self, response: requests.Response) -> dict[str, Any]:
        """Summarize a response and retain JSON only in memory for assertion extraction."""
        summary: dict[str, Any] = {
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type", "")[:100],
            "body_size": len(response.content),
        }
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, Mapping):
            summary["json_keys"] = sorted(str(key) for key in body.keys())[:100]
            summary["json_body"] = body
        elif isinstance(body, list):
            summary["json_items"] = len(body)
            summary["json_body"] = body
        return summary

    @staticmethod
    def _render(value: Any, context: Mapping[str, Any]) -> Any:
        """Render simple placeholders without evaluating arbitrary expressions."""
        if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
            return context.get(value[2:-2].strip(), value)
        if isinstance(value, list):
            return [APIExecutor._render(item, context) for item in value]
        if isinstance(value, Mapping):
            return {key: APIExecutor._render(item, context) for key, item in value.items()}
        return value

    @staticmethod
    def _render_mapping(value: Any, context: Mapping[str, Any]) -> dict[str, Any] | None:
        """Validate and render optional query parameters."""
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ExecutorConfigurationError("请求 params 必须是 JSON 对象。", "invalid_request_params")
        return {str(key): APIExecutor._render(item, context) for key, item in value.items()}

    @staticmethod
    def _json_path_value(value: Any, path: str) -> Any:
        """Read a bounded dotted JSON path without executing expressions."""
        current = value
        for part in path.strip(".").split("."):
            if isinstance(current, Mapping) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                current = current[int(part)]
            else:
                return None
        return current

    @classmethod
    def _json_path_exists(cls, value: Any, path: str) -> bool:
        """Return whether a JSON path resolves to a non-null value."""
        return cls._json_path_value(value, path) is not None

    @staticmethod
    def _count(value: Any) -> int:
        """Normalize script-provided counters without trusting arbitrary types."""
        return value if isinstance(value, int) and value >= 0 else 0

    @classmethod
    def _redact_json(cls, value: Any) -> list[dict[str, Any]]:
        """Keep script details JSON-shaped while masking sensitive-key values."""
        if not isinstance(value, list):
            return []
        sensitive_markers = ("password", "passwd", "token", "authorization", "api_key", "apikey", "secret")

        def sanitize(item: Any) -> Any:
            if isinstance(item, Mapping):
                return {
                    str(key): "<redacted>" if any(marker in str(key).casefold() for marker in sensitive_markers) else sanitize(child)
                    for key, child in item.items()
                }
            if isinstance(item, list):
                return [sanitize(child) for child in item]
            return item

        return [sanitize(item) for item in value if isinstance(item, Mapping)]


__all__ = ["APIExecutor"]
