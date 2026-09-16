"""Generate safe, data-driven pytest modules from structured API cases."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from apps.tests.models import TestCase

if TYPE_CHECKING:
    from apps.tests.executor.base import BaseExecutor


class PytestGenerationError(ValueError):
    """Report invalid case data before generating executable source."""

    def __init__(self, message: str, code: str = "invalid_pytest_case") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class GeneratedPytest:
    """Hold generated source and bounded generation metadata."""

    filename: str
    source: str
    case_count: int
    data_set_count: int

    def as_dict(self) -> dict[str, Any]:
        """Return generation metadata without duplicating generated source."""
        return {
            "filename": self.filename,
            "case_count": self.case_count,
            "data_set_count": self.data_set_count,
            "source_length": len(self.source),
        }


class PytestGenerator:
    """Convert API cases into deterministic pytest+requests source."""

    MAX_CASES = 256
    MAX_STEPS_PER_CASE = 128
    MAX_DATA_SETS_PER_CASE = 256
    MAX_SOURCE_LENGTH = 1_000_000
    ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
    SENSITIVE_KEY_MARKERS = ("password", "passwd", "token", "authorization", "api_key", "apikey", "secret", "cookie")

    def generate(
        self,
        cases: list[dict[str, Any]] | tuple[dict[str, Any], ...] | list[TestCase] | tuple[TestCase, ...],
        *,
        filename: str = "test_generated_api.py",
    ) -> GeneratedPytest:
        """Generate a deterministic module with one parametrized row per data set."""
        self._validate_filename(filename)
        if not isinstance(cases, (list, tuple)) or not cases:
            raise PytestGenerationError("接口测试用例必须是非空数组。", "empty_cases")
        if len(cases) > self.MAX_CASES:
            raise PytestGenerationError("接口测试用例数量超过安全上限。", "too_many_cases")
        normalized = [self._normalize_case(case, index) for index, case in enumerate(cases, start=1)]
        rows = [row for case in normalized for row in self._rows(case)]
        source = self._render_source(rows)
        if len(source) > self.MAX_SOURCE_LENGTH:
            raise PytestGenerationError("生成的 pytest 源码超过安全上限。", "generated_source_too_large")
        return GeneratedPytest(filename, source, len(normalized), len(rows))

    def write_to_workspace(self, executor: BaseExecutor, generated: GeneratedPytest) -> Path:
        """Write generated UTF-8 source through the executor workspace boundary."""
        return executor.write_workspace_file(generated.filename, generated.source)

    def _normalize_case(self, case: dict[str, Any] | TestCase, index: int) -> dict[str, Any]:
        """Normalize one mapping or persisted TestCase into JSON-safe fields."""
        if isinstance(case, TestCase):
            raw: dict[str, Any] = {
                "id": case.case_id,
                "title": case.title,
                "steps": case.steps,
                "input_data": case.input_data,
            }
        elif isinstance(case, dict):
            raw = case
        else:
            raise PytestGenerationError(f"第 {index} 条用例必须是对象。", "invalid_case")
        case_id = str(raw.get("case_id") or raw.get("id") or f"generated-{index:03d}").strip()
        if not case_id:
            raise PytestGenerationError(f"第 {index} 条用例缺少有效编号。", "invalid_case_id")
        title = str(raw.get("title") or case_id).strip()[:500]
        steps = raw.get("steps")
        if not isinstance(steps, list) or not steps:
            raise PytestGenerationError(f"用例 {case_id} 缺少结构化 steps。", "invalid_steps")
        if len(steps) > self.MAX_STEPS_PER_CASE:
            raise PytestGenerationError(f"用例 {case_id} 步骤数量超过安全上限。", "too_many_steps")
        normalized_steps = [self._normalize_step(step, case_id, step_index) for step_index, step in enumerate(steps, 1)]
        input_data = raw.get("input_data") if isinstance(raw.get("input_data"), dict) else {}
        data_sets = raw.get("data_sets") or raw.get("data") or input_data.get("data_sets")
        if data_sets is None:
            data_sets = [input_data]
        if not isinstance(data_sets, list) or not data_sets:
            raise PytestGenerationError(f"用例 {case_id} 的数据集必须是非空数组。", "invalid_data_sets")
        if len(data_sets) > self.MAX_DATA_SETS_PER_CASE:
            raise PytestGenerationError(f"用例 {case_id} 数据集数量超过安全上限。", "too_many_data_sets")
        for data_index, data_set in enumerate(data_sets, 1):
            self._validate_json_value(data_set, f"用例 {case_id} 数据集 {data_index}")
            if not isinstance(data_set, dict):
                raise PytestGenerationError(f"用例 {case_id} 数据集必须是 JSON 对象。", "invalid_data_set")
        return {
            "case_id": case_id,
            "title": title,
            "steps": normalized_steps,
            "data_sets": [self._sanitize_json_value(data_set) for data_set in data_sets],
        }

    def _normalize_step(self, step: Any, case_id: str, step_index: int) -> dict[str, Any]:
        """Validate request and assertion fields without evaluating user text."""
        if not isinstance(step, dict):
            raise PytestGenerationError(f"用例 {case_id} 第 {step_index} 步必须是对象。", "invalid_step")
        method = str(step.get("method") or "GET").upper()
        if method not in self.ALLOWED_METHODS:
            raise PytestGenerationError(f"用例 {case_id} 第 {step_index} 步请求方法不支持。", "invalid_http_method")
        raw_url = step.get("path") or step.get("url") or step.get("endpoint")
        if not isinstance(raw_url, str) or not raw_url.strip():
            raise PytestGenerationError(f"用例 {case_id} 第 {step_index} 步缺少 path/url。", "request_url_required")
        parsed = urlsplit(raw_url)
        if parsed.username or parsed.password:
            raise PytestGenerationError(f"用例 {case_id} 第 {step_index} 步地址不能包含认证信息。", "request_url_credentials")
        normalized: dict[str, Any] = {"method": method, "path": raw_url}
        for field in ("headers", "params", "json", "body", "expected_status", "status_code", "assertions"):
            if field in step:
                self._validate_json_value(step[field], f"用例 {case_id} 第 {step_index} 步 {field}")
                normalized[field] = self._sanitize_json_value(step[field])
        for field in ("headers", "params"):
            if field in normalized and not isinstance(normalized[field], dict):
                raise PytestGenerationError(f"用例 {case_id} 第 {step_index} 步 {field} 必须是对象。", "invalid_step_shape")
        expected = normalized.get("expected_status", normalized.get("status_code"))
        if expected is not None:
            accepted = expected if isinstance(expected, list) else [expected]
            if not accepted or any(isinstance(item, bool) or not isinstance(item, int) or not 100 <= item <= 599 for item in accepted):
                raise PytestGenerationError(f"用例 {case_id} 第 {step_index} 步状态码断言无效。", "invalid_status_assertion")
        if "assertions" in normalized:
            assertions = normalized["assertions"]
            if not isinstance(assertions, list):
                raise PytestGenerationError(f"用例 {case_id} 第 {step_index} 步断言必须是数组。", "invalid_assertions")
            for assertion in assertions:
                if not isinstance(assertion, dict) or not isinstance(assertion.get("json_path", assertion.get("field")), str):
                    raise PytestGenerationError(f"用例 {case_id} 第 {step_index} 步 JSON 断言无效。", "invalid_assertion")
        return normalized

    def _rows(self, case: dict[str, Any]) -> list[dict[str, Any]]:
        """Expand one case into stable data-driven pytest rows."""
        return [
            {"case_id": case["case_id"], "title": case["title"], "steps": case["steps"], "data": data, "index": index}
            for index, data in enumerate(case["data_sets"], 1)
        ]

    def _render_source(self, rows: list[dict[str, Any]]) -> str:
        """Render only validated Python literals into a fixed runtime template."""
        rows_literal = repr(rows)
        ids_literal = repr([f"{row['case_id']}-{row['index']}" for row in rows])
        return f'''"""Generated API tests; source data is deterministic and reviewable."""

import os
from urllib.parse import urlsplit

import pytest
import requests


TEST_ROWS = {rows_literal}
TEST_IDS = {ids_literal}
ALLOWED_METHODS = {repr(sorted(self.ALLOWED_METHODS))}


def _render(value, data):
    """Render exact placeholders without evaluating expressions."""
    if isinstance(value, dict) and set(value) == {{"__aits_env__"}}:
        return os.environ.get(value["__aits_env__"], "")
    if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
        return data.get(value[2:-2].strip(), value)
    if isinstance(value, list):
        return [_render(item, data) for item in value]
    if isinstance(value, dict):
        return {{key: _render(item, data) for key, item in value.items()}}
    return value


def _json_path_exists(value, path):
    """Check a dotted JSON path without evaluating arbitrary code."""
    current = value
    for part in path.strip(".").split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False
    return current is not None


def _url(path):
    """Resolve only relative or same-origin URLs against the runtime environment."""
    base = os.environ.get("AITS_TEST_BASE_URL", "").rstrip("/")
    if not base:
        pytest.skip("未配置 AITS_TEST_BASE_URL，跳过目标接口调用。")
    parsed = urlsplit(path)
    base_parts = urlsplit(base)
    if parsed.username or parsed.password:
        raise AssertionError("接口地址不能包含认证信息")
    if parsed.scheme or parsed.netloc:
        if (parsed.scheme, parsed.netloc) != (base_parts.scheme, base_parts.netloc):
            raise AssertionError("接口地址必须属于当前测试环境")
        return path
    return f"{{base}}/{{path.lstrip('/')}}"


@pytest.mark.parametrize("row", TEST_ROWS, ids=TEST_IDS)
def test_generated_api_case(row):
    """Execute generated steps with requests and data-driven input."""
    session = requests.Session()
    context = dict(row["data"])
    try:
        for step in row["steps"]:
            method = step["method"]
            assert method in ALLOWED_METHODS
            headers = _render(step.get("headers", {{}}), context)
            params = _render(step.get("params"), context)
            body = step.get("json", step.get("body"))
            response = session.request(
                method,
                _url(_render(step["path"], context)),
                headers=headers,
                params=params,
                json=_render(body, context),
                timeout=30,
            )
            expected = step.get("expected_status", step.get("status_code"))
            accepted = expected if isinstance(expected, list) else [expected] if expected is not None else list(range(200, 300))
            assert response.status_code in accepted
            try:
                response_body = response.json()
            except ValueError:
                response_body = None
            for assertion in step.get("assertions", []):
                path = assertion.get("json_path", assertion.get("field"))
                assert isinstance(path, str) and _json_path_exists(response_body, path) == assertion.get("exists", True)
    finally:
        session.close()
'''

    @staticmethod
    def _validate_filename(filename: str) -> None:
        """Allow only a relative pytest module filename."""
        path = Path(filename)
        if path.name != filename or path.suffix != ".py" or not filename.startswith("test_"):
            raise PytestGenerationError("生成文件名必须是 test_*.py 的相对文件名。", "invalid_filename")

    @classmethod
    def _sanitize_json_value(cls, value: Any, key_hint: str = "") -> Any:
        """Replace sensitive leaves with runtime environment references."""
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                normalized_key = str(key).casefold().replace("-", "_")
                if any(marker in normalized_key for marker in cls.SENSITIVE_KEY_MARKERS):
                    env_key = "AITS_TEST_SECRET_" + re.sub(r"[^A-Z0-9_]", "_", str(key).upper())
                    sanitized[str(key)] = {"__aits_env__": env_key[:80]}
                else:
                    sanitized[str(key)] = cls._sanitize_json_value(item, str(key))
            return sanitized
        if isinstance(value, list):
            return [cls._sanitize_json_value(item, key_hint) for item in value]
        return value

    @classmethod
    def _validate_json_value(cls, value: Any, field_name: str) -> None:
        """Reject values that cannot be safely embedded as JSON-compatible literals."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return
        if isinstance(value, list):
            for item in value:
                cls._validate_json_value(item, field_name)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise PytestGenerationError(f"{field_name} 的键必须是字符串。", "invalid_json_value")
                cls._validate_json_value(item, field_name)
            return
        raise PytestGenerationError(f"{field_name} 包含不可生成的值。", "invalid_json_value")


__all__ = ["GeneratedPytest", "PytestGenerationError", "PytestGenerator"]
