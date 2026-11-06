"""Adversarial contract for the gate-coverage tripwire.

Two halves: the script's discover-and-fail-closed logic, and the guarantee that
every default stamp's declared TEST_SUITES matches what it actually ships, so a
fresh project never fails its own new gate on day one.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "template" / "scripts" / "check-gate-coverage.sh"
GENERATE = ROOT / "bin" / "generate.py"
EXAMPLES = sorted((ROOT / "examples").glob("*.answers.json"))
BASH = os.environ.get("GATE_COVERAGE_BASH", "bash")


def run_script(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, str(SCRIPT), *args],
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "LC_ALL": "C"},
    )


class GateCoverageLogicContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.repo = Path(self.tempdir.name) / "repo"
        self.repo.mkdir()

    def mkdir(self, rel: str) -> None:
        (self.repo / rel).mkdir(parents=True, exist_ok=True)

    def test_listed_roots_pass(self) -> None:
        self.mkdir("scripts/tests")
        self.mkdir("backend/tests")
        result = run_script(self.repo, "scripts/tests", "backend/tests")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("none unlisted", result.stdout)

    def test_unlisted_root_fails_and_is_named(self) -> None:
        self.mkdir("scripts/tests")
        self.mkdir("backend/tests")
        self.mkdir("widgets/tests")  # exists but no runner declares it
        result = run_script(self.repo, "scripts/tests", "backend/tests")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("gate-coverage:unlisted-suite", result.stderr)
        self.assertIn("widgets/tests", result.stderr)
        # Content discipline: the offending path is named; nothing else leaks.
        self.assertNotIn("backend/tests", result.stderr)

    def test_deeply_nested_root_is_found(self) -> None:
        self.mkdir("scripts/tests")
        self.mkdir("a/b/c/tests")
        result = run_script(self.repo, "scripts/tests")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("a/b/c/tests", result.stderr)

    def test_singular_test_dir_is_discovered(self) -> None:
        self.mkdir("scripts/tests")
        self.mkdir("test")  # node-notifier style singular root
        undeclared = run_script(self.repo, "scripts/tests")
        self.assertEqual(undeclared.returncode, 1, undeclared.stderr)
        self.assertIn("test", undeclared.stderr)
        declared = run_script(self.repo, "scripts/tests", "test")
        self.assertEqual(declared.returncode, 0, declared.stdout + declared.stderr)

    def test_build_and_vendor_dirs_are_pruned(self) -> None:
        self.mkdir("scripts/tests")
        self.mkdir("node_modules/pkg/tests")  # vendored dependency tests
        self.mkdir("build/tests")
        self.mkdir("frontend/.next/tests")
        self.mkdir("services/.dart_tool/x/test")
        result = run_script(self.repo, "scripts/tests")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("none unlisted", result.stdout)


class GateCoverageStampContract(unittest.TestCase):
    """Every default stamp ships exactly the suites its Makefile declares."""

    def _stamp(self, answers: Path, out: Path) -> None:
        subprocess.run(
            ["python3", str(GENERATE), "--values", str(answers), "--output", str(out)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    @staticmethod
    def _declared_suites(makefile_text: str) -> list[str] | None:
        match = re.search(
            r"^TEST_SUITES\s*:=\s*(.*)$", makefile_text, re.MULTILINE
        )
        if match is None:
            return None
        return match.group(1).split()

    def test_every_stack_declares_matching_suites_and_wires_the_gate(self) -> None:
        self.assertTrue(EXAMPLES, "no example answers files found")
        with tempfile.TemporaryDirectory() as temp:
            for answers in EXAMPLES:
                with self.subTest(answers=answers.name):
                    out = Path(temp) / answers.stem
                    self._stamp(answers, out)
                    makefile = (out / "Makefile").read_text(encoding="utf-8")

                    declared = self._declared_suites(makefile)
                    self.assertIsNotNone(
                        declared, f"{answers.name}: no TEST_SUITES declaration"
                    )
                    # The gate defines its target and runs inside the Tests job.
                    self.assertRegex(
                        makefile,
                        r"(?m)^check-gate-coverage:",
                    )
                    self.assertRegex(
                        makefile,
                        r"(?m)^test:.*\bcheck-gate-coverage\b",
                    )
                    # The declared suites make a fresh stamp clean.
                    result = run_script(out, *declared)
                    self.assertEqual(
                        result.returncode,
                        0,
                        f"{answers.name}: {result.stdout}{result.stderr}",
                    )
                    self.assertIn("none unlisted", result.stdout)

    def test_listed_in_generator_ci(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("tests.test_gate_coverage_contract", workflow)


if __name__ == "__main__":
    unittest.main()
