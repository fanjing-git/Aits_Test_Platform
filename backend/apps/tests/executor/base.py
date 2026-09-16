"""Safe, reusable base class for local test executors."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any, Sequence

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from apps.tests.models import TestRun


class ExecutorConfigurationError(ValueError):
    """Report an invalid execution context before starting a subprocess."""

    def __init__(self, message: str, code: str = "executor_configuration_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Expose a stable, redacted result shape to concrete executors."""

    status: str
    exit_code: int | None
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_ms: int = 0
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error_code: str = ""
    error_message: str = ""
    details: list[dict[str, Any]] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)
    workspace: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable copy suitable for a result service."""
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "details": [dict(item) for item in self.details],
            "environment": dict(self.environment),
            "workspace": self.workspace,
        }


class BaseExecutor(ABC):
    """Provide environment, workspace, pytest, and parsing primitives."""

    _SUMMARY_PATTERN = re.compile(r"(?P<count>\d+)\s+(?P<label>passed|failed|skipped|errors?|xfailed|xpassed)")
    _DURATION_PATTERN = re.compile(r"\bin\s+(?P<seconds>\d+(?:\.\d+)?)s\b")
    _SECRET_PATTERN = re.compile(
        r"(?i)(\b(?:password|passwd|token|authorization|api[_-]?key|secret)\b\s*[:=]\s*)([^\s,;]+)"
    )
    _JSON_SECRET_PATTERN = re.compile(
        r"(?i)([\"']?(?:password|passwd|token|authorization|api[_-]?key|secret)[\"']?\s*:\s*)([^,}\n]+)"
    )
    _BEARER_PATTERN = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+")
    _WORKSPACE_MARKER = ".aits-workspace"

    def __init__(
        self,
        run: TestRun,
        *,
        workspace_root: str | Path | None = None,
        timeout_seconds: int = 300,
    ) -> None:
        """Create an executor bound to one persisted test run."""
        if not run.pk or not run.project_id:
            raise ExecutorConfigurationError("测试执行必须先保存并关联项目。", "run_not_persisted")
        if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 3600:
            raise ExecutorConfigurationError("执行超时必须是 1 到 3600 秒。", "invalid_timeout")
        self.run = run
        configured_root = workspace_root or getattr(
            settings, "TEST_EXECUTION_ROOT", Path(settings.BASE_DIR) / ".runtime" / "test-executions"
        )
        self.workspace_root = Path(configured_root).expanduser().resolve()
        self.timeout_seconds = timeout_seconds
        self._workspace: Path | None = None

    @property
    def workspace(self) -> Path | None:
        """Return the prepared workspace, or ``None`` before preparation."""
        return self._workspace

    @abstractmethod
    def execute(self) -> ExecutionResult:
        """Execute the concrete test type and return a unified result."""

    def environment_context(self) -> dict[str, Any]:
        """Return environment metadata without exposing credentials or values."""
        environment = self._load_environment()
        if environment is None:
            return {"selected": False, "status": "not_selected"}
        if environment.project_id != self.run.project_id:
            return {
                "selected": True,
                "status": "invalid_project",
                "environment_id": str(environment.pk),
            }
        return {
            "selected": True,
            "environment_id": str(environment.pk),
            "name": environment.name,
            "base_url": environment.base_url,
            "status": environment.status,
            "health_status": environment.health_status,
            "auth_configured": bool(environment.auth_config),
            "variables_configured": bool(environment.variables),
        }

    def ensure_environment_ready(self) -> dict[str, Any]:
        """Validate project ownership and operator health before execution."""
        environment = self._load_environment()
        if environment is None:
            raise ExecutorConfigurationError("执行前必须选择测试环境。", "environment_not_selected")
        if environment.project_id != self.run.project_id:
            raise ExecutorConfigurationError("测试环境必须属于执行所在项目。", "environment_project_mismatch")
        if environment.status != environment.Status.AVAILABLE:
            raise ExecutorConfigurationError("测试环境当前不可执行，请先确认环境状态。", "environment_unavailable")
        if environment.health_status == environment.HealthStatus.UNHEALTHY:
            raise ExecutorConfigurationError("测试环境健康检查异常，已阻止执行。", "environment_unhealthy")
        return self.environment_context()

    def prepare_workspace(self) -> Path:
        """Create an isolated workspace scoped to the project and test run."""
        workspace = self.workspace_root / str(self.run.project_id) / str(self.run.pk)
        self._assert_within(workspace, self.workspace_root)
        workspace.mkdir(parents=True, exist_ok=True)
        marker = workspace / self._WORKSPACE_MARKER
        marker.write_text("AITS test execution workspace\n", encoding="utf-8")
        self._workspace = workspace
        return workspace

    def resolve_workspace_path(self, relative_path: str | Path) -> Path:
        """Resolve a relative path and reject traversal outside the workspace."""
        workspace = self._workspace or self.prepare_workspace()
        candidate_path = Path(relative_path)
        if candidate_path.is_absolute() or "\x00" in str(candidate_path):
            raise ExecutorConfigurationError("工作目录文件必须使用安全的相对路径。", "invalid_workspace_path")
        candidate = (workspace / candidate_path).resolve()
        self._assert_within(candidate, workspace)
        return candidate

    def write_workspace_file(self, relative_path: str | Path, content: str) -> Path:
        """Write UTF-8 test source into the isolated workspace."""
        if not isinstance(content, str):
            raise ExecutorConfigurationError("工作目录文件内容必须是文本。", "invalid_workspace_content")
        path = self.resolve_workspace_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def cleanup_workspace(self) -> None:
        """Remove only a workspace created by this executor instance."""
        if self._workspace is None:
            return
        self._assert_within(self._workspace, self.workspace_root)
        marker = self._workspace / self._WORKSPACE_MARKER
        if marker.is_file() and marker.read_text(encoding="utf-8") == "AITS test execution workspace\n":
            shutil.rmtree(self._workspace)
        self._workspace = None

    def run_pytest(
        self,
        test_path: str | Path,
        *,
        extra_args: Sequence[str] = (),
        timeout_seconds: int | None = None,
    ) -> ExecutionResult:
        """Run pytest without a shell and parse a redacted unified result."""
        workspace = self._workspace or self.prepare_workspace()
        test_file = self.resolve_workspace_path(test_path)
        if not test_file.is_file():
            raise ExecutorConfigurationError("pytest 文件不存在于执行工作目录。", "pytest_file_not_found")
        command_args = list(extra_args)
        if any(not isinstance(item, str) or "\x00" in item for item in command_args):
            raise ExecutorConfigurationError("pytest 参数必须是安全文本。", "invalid_pytest_argument")
        timeout = self.timeout_seconds if timeout_seconds is None else timeout_seconds
        if not isinstance(timeout, int) or not 1 <= timeout <= 3600:
            raise ExecutorConfigurationError("pytest 超时必须是 1 到 3600 秒。", "invalid_timeout")
        command = [sys.executable, "-m", "pytest", str(test_file.relative_to(workspace)), "-q", *command_args]
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        base_url = self.environment_context().get("base_url")
        if isinstance(base_url, str) and base_url:
            environment["AITS_TEST_BASE_URL"] = base_url
        started = monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=workspace,
                capture_output=True,
                check=False,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return self.parse_pytest_output(
                exit_code=None,
                stdout=self._output_text(exc.stdout),
                stderr=self._output_text(exc.stderr),
                duration_ms=self._duration_ms(started),
                timed_out=True,
                error_code="pytest_timeout",
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return self.parse_pytest_output(
                exit_code=None,
                stdout="",
                stderr="",
                duration_ms=self._duration_ms(started),
                error_code="pytest_process_error",
                error_message="pytest 进程启动失败，请检查执行环境。",
                exception_detail=str(exc),
            )
        return self.parse_pytest_output(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=self._duration_ms(started),
        )

    def parse_pytest_output(
        self,
        *,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        duration_ms: int,
        timed_out: bool = False,
        error_code: str = "",
        error_message: str = "",
        exception_detail: str = "",
    ) -> ExecutionResult:
        """Parse pytest terminal counts and map failures to platform states."""
        safe_stdout = self._redact_output(stdout)
        safe_stderr = self._redact_output(stderr)
        combined = f"{safe_stdout}\n{safe_stderr}"
        counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
        summary_lines = [line for line in combined.splitlines() if self._DURATION_PATTERN.search(line)]
        summary = summary_lines[-1] if summary_lines else combined
        for match in self._SUMMARY_PATTERN.finditer(summary):
            label = match.group("label")
            count = int(match.group("count"))
            if label in counts:
                counts[label] += count
            elif label == "error":
                counts["errors"] += count
        parsed_duration = self._DURATION_PATTERN.search(summary)
        if parsed_duration:
            duration_ms = max(duration_ms, round(float(parsed_duration.group("seconds")) * 1000))
        if timed_out:
            status = "error"
            error_code = error_code or "pytest_timeout"
            error_message = error_message or "pytest 执行超时。"
        elif counts["failed"]:
            status = "failed"
        elif counts["errors"]:
            status = "error"
        elif exit_code == 5 or (exit_code == 0 and not any(counts.values())):
            status = "skipped"
        elif exit_code == 0:
            status = "passed"
        else:
            status = "error"
            error_code = error_code or "pytest_nonzero_exit"
            error_message = error_message or "pytest 执行未正常完成。"
        return ExecutionResult(
            status=status,
            exit_code=exit_code,
            passed=counts["passed"],
            failed=counts["failed"],
            skipped=counts["skipped"],
            errors=counts["errors"],
            duration_ms=max(0, duration_ms),
            stdout=safe_stdout,
            stderr=safe_stderr,
            timed_out=timed_out,
            error_code=error_code,
            error_message=error_message or exception_detail,
            environment=self.environment_context(),
            workspace=str(self._workspace) if self._workspace else "",
        )

    def _load_environment(self) -> Any | None:
        """Load the selected environment while keeping missing relations safe."""
        if not self.run.environment_id:
            return None
        try:
            return self.run.environment
        except ObjectDoesNotExist:
            return None

    @classmethod
    def _assert_within(cls, path: Path, root: Path) -> None:
        """Raise when a resolved path escapes its approved root."""
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ExecutorConfigurationError("路径超出执行工作目录范围。", "workspace_escape") from exc

    @staticmethod
    def _duration_ms(started: float) -> int:
        """Convert elapsed monotonic time to a nonnegative integer."""
        return max(0, round((monotonic() - started) * 1000))

    @staticmethod
    def _output_text(value: str | bytes | None) -> str:
        """Normalize timeout output across Python subprocess text modes."""
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    @classmethod
    def _redact_output(cls, value: str) -> str:
        """Remove common credential-shaped values from process output."""
        redacted = cls._SECRET_PATTERN.sub(r"\1<redacted>", value)
        redacted = cls._JSON_SECRET_PATTERN.sub(r"\1<redacted>", redacted)
        return cls._BEARER_PATTERN.sub(r"\1<redacted>", redacted)
