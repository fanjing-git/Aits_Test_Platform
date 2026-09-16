"""Focused tests for the T057 APIExecutor modes and safety boundaries."""

import json
import tempfile

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase as DjangoTestCase

from apps.environments.models import Environment
from apps.projects.models import Project
from apps.tests.executor.api_executor import APIExecutor
from apps.tests.models import TestCase, TestRun


class FakeResponse:
    """Minimal response double exposing only fields used by APIExecutor."""

    def __init__(self, status_code: int, body: object) -> None:
        self.status_code = status_code
        self.headers = {"content-type": "application/json"}
        self._body = body
        self.content = json.dumps(body).encode("utf-8")

    def json(self) -> object:
        """Return the configured JSON body."""
        return self._body


class FakeSession:
    """Deterministic request session that never touches a real network."""

    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        """Record a request and return or raise the next configured outcome."""
        self.calls.append({"method": method, "url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self) -> None:
        """Match the requests session lifecycle API."""


class APIExecutorTests(DjangoTestCase):
    """Verify modes, aggregation, data flow, and outbound request boundaries."""

    def setUp(self) -> None:
        """Create a ready environment with encrypted authentication metadata."""
        user = get_user_model().objects.create_user(username="t057-owner", password="safe-test-password")
        project = Project.objects.create(name="T057 Project", created_by=user)
        environment = Environment.objects.create(
            project=project,
            name=Environment.Name.TEST,
            base_url="https://test.example.com/api",
            status=Environment.Status.AVAILABLE,
            health_status=Environment.HealthStatus.HEALTHY,
            auth_config={"token": "secret-not-returned"},
        )
        self.run = TestRun.objects.create(project=project, environment=environment, name="T057 run")
        self.temp_root = tempfile.TemporaryDirectory(prefix="aits-t057-")
        self.addCleanup(self.temp_root.cleanup)

    def make_case(self, case_id: str, steps: list[dict[str, object]]) -> TestCase:
        """Create a structured API case for executor tests."""
        case = TestCase(
            project=self.run.project,
            case_id=case_id,
            title=case_id,
            steps=steps,
            input_data={},
            expected_result="请求成功。",
            case_type=TestCase.CaseType.API,
        )
        case.full_clean()
        case.save()
        return case

    def executor(self, session: FakeSession | None = None) -> APIExecutor:
        """Build an executor with a test-only workspace and optional session double."""
        return APIExecutor(self.run, session=session, workspace_root=self.temp_root.name, timeout_seconds=5)

    def test_immediate_mode_executes_one_case_with_environment_auth(self) -> None:
        """Immediate mode sends one request and returns a safe passed summary."""
        case = self.make_case("TC-T057-001", [{"method": "GET", "path": "/health"}])
        self.run.test_cases.add(case)
        session = FakeSession([FakeResponse(200, {"ok": True})])

        result = self.executor(session).execute()

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.passed, 1)
        self.assertEqual(session.calls[0]["url"], "https://test.example.com/api/health")
        self.assertEqual(session.calls[0]["headers"], {"Authorization": "Bearer secret-not-returned"})
        self.assertNotIn("secret-not-returned", str(result.as_dict()))

    def test_immediate_mode_rejects_multiple_cases_without_requests(self) -> None:
        """Immediate mode must remain a single-interface operation."""
        first = self.make_case("TC-T057-002", [{"path": "/one"}])
        second = self.make_case("TC-T057-003", [{"path": "/two"}])
        self.run.test_cases.add(first, second)
        session = FakeSession([])

        result = self.executor(session).execute()

        self.assertEqual(result.error_code, "immediate_case_count")
        self.assertEqual(session.calls, [])

    def test_full_mode_aggregates_failed_api_case(self) -> None:
        """Full mode executes all selected cases and aggregates statuses."""
        first = self.make_case("TC-T057-004", [{"path": "/one"}])
        second = self.make_case("TC-T057-005", [{"path": "/two"}])
        self.run.mode = TestRun.Mode.FULL
        self.run.test_cases.add(first, second)
        session = FakeSession([FakeResponse(200, {}), FakeResponse(500, {"error": "blocked"})])

        result = self.executor(session).execute()

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.passed, 1)
        self.assertEqual(result.failed, 1)
        self.assertNotIn("blocked", str(result.as_dict()))

    def test_data_flow_injects_memory_only_value_into_next_request(self) -> None:
        """Configured response fields can feed a later request without persistence."""
        case = self.make_case(
            "TC-T057-006",
            [
                {"path": "/create"},
                {"path": "/detail", "json": {"id": "{{order_id}}"}},
            ],
        )
        case.input_data = {"data_flow": [
            {
                "source": {"step_id": "step-1", "field": "data.id"},
                "target": {"step_id": "step-2", "field": "order_id"},
            }
        ]}
        case.save(update_fields=["input_data"])
        self.run.test_cases.add(case)
        session = FakeSession([FakeResponse(200, {"data": {"id": "ID-1"}}), FakeResponse(200, {"ok": True})])

        result = self.executor(session).execute()

        self.assertEqual(result.status, "passed")
        self.assertEqual(session.calls[1]["json"], {"id": "ID-1"})
        self.assertNotIn("ID-1", str(result.as_dict()))

    def test_script_mode_requires_json_contract_and_runs_in_workspace(self) -> None:
        """Script mode executes a relative script and accepts structured JSON output."""
        self.run.mode = TestRun.Mode.SCRIPT
        self.run.execution_config = {"script_path": "script.py"}
        executor = self.executor()
        executor.write_workspace_file("script.py", "import json\nprint(json.dumps({'status': 'passed', 'passed': 2}))\n")

        result = executor.execute()

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.passed, 2)

    def test_origin_mismatch_and_request_timeout_are_safe_errors(self) -> None:
        """Cross-origin targets and transport timeouts must not leak or bypass policy."""
        case = self.make_case("TC-T057-007", [{"path": "https://attacker.example/steal"}])
        self.run.test_cases.add(case)
        session = FakeSession([])
        result = self.executor(session).execute()
        self.assertEqual(result.details[0]["error_code"], "request_origin_mismatch")
        self.assertEqual(session.calls, [])

        self.run.test_cases.clear()
        timeout_case = self.make_case("TC-T057-008", [{"path": "/slow"}])
        self.run.test_cases.add(timeout_case)
        timeout_session = FakeSession([requests.Timeout()])
        timeout_result = self.executor(timeout_session).execute()
        self.assertEqual(timeout_result.status, "error")
        self.assertEqual(timeout_result.details[0]["error_code"], "request_timeout")
