"""Focused tests for the T058 PytestGenerator contract."""

import ast
import os
import subprocess
import sys
import tempfile

from django.test import SimpleTestCase

from apps.tests.generator.pytest_generator import PytestGenerationError, PytestGenerator


class PytestGeneratorTests(SimpleTestCase):
    """Verify deterministic data-driven source generation and input boundaries."""

    def setUp(self) -> None:
        """Create one generator and a structured API case."""
        self.generator = PytestGenerator()
        self.case = {
            "case_id": "TC-T058-001",
            "title": "数据驱动登录",
            "steps": [
                {
                    "method": "POST",
                    "path": "/login",
                    "json": {"username": "{{username}}", "password": "{{password}}"},
                    "expected_status": 200,
                    "assertions": [{"json_path": "data.token", "exists": True}],
                }
            ],
            "data_sets": [
                {"username": "alice", "password": "masked-a"},
                {"username": "bob", "password": "masked-b"},
            ],
        }

    def test_generates_valid_parametrized_pytest_source(self) -> None:
        """Generated code must parse and expose one row per data set."""
        generated = self.generator.generate([self.case])

        ast.parse(generated.source)
        self.assertEqual(generated.case_count, 1)
        self.assertEqual(generated.data_set_count, 2)
        self.assertIn("pytest.mark.parametrize", generated.source)
        self.assertIn("TC-T058-001-1", generated.source)
        self.assertIn("TC-T058-001-2", generated.source)
        self.assertNotIn("masked-a", generated.source)
        self.assertNotIn("masked-b", generated.source)

    def test_generated_module_is_collectable_without_target_calls(self) -> None:
        """Generated pytest is executable and skips safely when no target is configured."""
        generated = self.generator.generate([self.case])
        with tempfile.TemporaryDirectory(prefix="aits-t058-generated-") as directory:
            path = f"{directory}/{generated.filename}"
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(generated.source)
            environment = os.environ.copy()
            environment.pop("AITS_TEST_BASE_URL", None)
            environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", generated.filename, "-q"],
                cwd=directory,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=15,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("2 skipped", completed.stdout)

    def test_accepts_persisted_case_shape_and_keeps_code_injection_as_data(self) -> None:
        """Case text is emitted as literals, never executable template syntax."""
        hostile = dict(self.case)
        hostile["title"] = "x'); __import__('os').system('bad') #"
        generated = self.generator.generate([hostile])

        ast.parse(generated.source)
        self.assertIn("__import__", generated.source)
        self.assertIn("title", generated.source)

    def test_rejects_invalid_steps_filename_and_non_json_values(self) -> None:
        """Invalid structures must fail before source generation."""
        invalid_steps = dict(self.case, steps=["POST /login"])
        with self.assertRaises(PytestGenerationError) as step_error:
            self.generator.generate([invalid_steps])
        self.assertEqual(step_error.exception.code, "invalid_step")

        with self.assertRaises(PytestGenerationError) as file_error:
            self.generator.generate([self.case], filename="generated.py")
        self.assertEqual(file_error.exception.code, "invalid_filename")

        invalid_value = dict(self.case, data_sets=[{"not_json": object()}])
        with self.assertRaises(PytestGenerationError) as value_error:
            self.generator.generate([invalid_value])
        self.assertEqual(value_error.exception.code, "invalid_json_value")

    def test_rejects_empty_and_oversized_input(self) -> None:
        """Generation limits protect workspace size and execution planning."""
        with self.assertRaises(PytestGenerationError) as empty_error:
            self.generator.generate([])
        self.assertEqual(empty_error.exception.code, "empty_cases")

        too_many = [dict(self.case, case_id=f"TC-T058-{index:03d}") for index in range(257)]
        with self.assertRaises(PytestGenerationError) as size_error:
            self.generator.generate(too_many)
        self.assertEqual(size_error.exception.code, "too_many_cases")
