"""Adversarial contract for the optional mutation-proof harness."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "template" / "scripts" / "mutation-check.sh"
CASES = ROOT / "template" / "scripts" / "mutation-cases.sh"
BASH = os.environ.get("MUTATION_CHECK_BASH", "bash")


class MutationCheckContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.repo = Path(self.tempdir.name) / "project"
        scripts = self.repo / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy2(SCRIPT, scripts / "mutation-check.sh")
        (scripts / "mutation-check.sh").chmod(0o755)
        shutil.copy2(CASES, scripts / "mutation-cases.sh")

    @property
    def target(self) -> Path:
        return self.repo / "src" / "odd target [x].txt"

    def write_target(self, content: bytes = b"prefix\r\nSAFE\xfftail") -> bytes:
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_bytes(content)
        self.target.chmod(0o640)
        return content

    def write_script(self, name: str, body: str) -> Path:
        path = self.repo / "scripts" / name
        path.write_text("#!/usr/bin/env bash\nset -u\n" + body, encoding="utf-8")
        path.chmod(0o755)
        return path

    def set_case(
        self,
        case_id: str,
        target: str,
        before: str,
        after: str,
        expected_status: int,
        command: list[str],
    ) -> None:
        args = [case_id, target, before, after, str(expected_status), "--", *command]
        line = "mutation_case " + " ".join(shlex.quote(value) for value in args) + "\n"
        (self.repo / "scripts" / "mutation-cases.sh").write_text(
            "#!/usr/bin/env bash\n" + line, encoding="utf-8"
        )

    def run_harness(
        self,
        *,
        env: dict[str, str] | None = None,
        timeout: float = 15,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, str(self.repo / "scripts" / "mutation-check.sh")],
            cwd=Path(self.tempdir.name),
            env={**os.environ, **(env or {})},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )

    @staticmethod
    def combined(result: subprocess.CompletedProcess[str]) -> str:
        return result.stdout + result.stderr

    def test_empty_plan_is_truthful_tool_light_skip(self) -> None:
        canary = Path(self.tempdir.name) / "canary"
        tool_bin = Path(self.tempdir.name) / "tool-bin"
        tool_bin.mkdir()
        for name in ("bash", "dirname"):
            source = shutil.which(name)
            self.assertIsNotNone(source)
            os.symlink(source, tool_bin / name)
        for name in ("perl", "sha256sum", "shasum", "cp", "stat", "mktemp"):
            path = tool_bin / name
            path.write_text(
                f"#!/bin/sh\nprintf invoked >> {shlex.quote(str(canary))}\nexit 99\n",
                encoding="utf-8",
            )
            path.chmod(0o755)

        result = self.run_harness(env={"PATH": str(tool_bin)})
        output = self.combined(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("mutation-check: SKIP cases=0 configured=0", output)
        self.assertFalse(canary.exists())
        self.assertFalse((self.repo / ".mutation-check.lock").exists())

    def test_killed_mutant_restores_dirty_bytes_mode_and_suppresses_output(self) -> None:
        original = self.write_target()
        original_mode = stat.S_IMODE(self.target.stat().st_mode)
        unrelated = self.repo / "unrelated dirty.txt"
        unrelated.write_bytes(b"uncommitted and untouched\n")
        marker = "SYNTHETIC_MUTATION_OUTPUT_DO_NOT_PRINT"
        self.write_script(
            "probe.sh",
            f"""
if grep -a -q BROKEN 'src/odd target [x].txt'; then
  printf '%s\\n' '{marker}'
  printf '%s\\n' '{marker}' >&2
  printf '%s\\n' "$MUTATION_CHECK_EVIDENCE_MARKER" > "$MUTATION_CHECK_EVIDENCE_FILE"
  exit 7
fi
grep -a -q SAFE 'src/odd target [x].txt'
""",
        )
        self.set_case(
            "M001",
            "src/odd target [x].txt",
            "SAFE",
            "BROKEN",
            7,
            ["bash", "scripts/probe.sh"],
        )

        result = self.run_harness()
        output = self.combined(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("mutation-check: PASS id=M001", output)
        self.assertIn("mutation-check: PASS cases=1 killed=1", output)
        self.assertNotIn(marker, output)
        self.assertNotIn("odd target", output)
        self.assertNotIn("SAFE", output)
        self.assertNotIn("BROKEN", output)
        self.assertEqual(self.target.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), original_mode)
        self.assertEqual(unrelated.read_bytes(), b"uncommitted and untouched\n")
        self.assertFalse((self.repo / ".mutation-check.lock").exists())

    def test_bsd_style_wc_padding_is_accepted(self) -> None:
        original = self.write_target()
        self.write_script(
            "bsd-wc-probe.sh",
            """
if grep -a -q BROKEN 'src/odd target [x].txt'; then
  printf '%s\\n' "$MUTATION_CHECK_EVIDENCE_MARKER" > "$MUTATION_CHECK_EVIDENCE_FILE"
  exit 7
fi
exit 0
""",
        )
        tool_bin = Path(self.tempdir.name) / "bsd-tools"
        tool_bin.mkdir()
        real_wc = shutil.which("wc")
        self.assertIsNotNone(real_wc)
        wc_wrapper = tool_bin / "wc"
        wc_wrapper.write_text(
            "#!/bin/sh\n"
            f"out=$({shlex.quote(real_wc)} \"$@\") || exit $?\n"
            "printf '   %s\\n' \"$out\"\n",
            encoding="utf-8",
        )
        wc_wrapper.chmod(0o755)
        self.set_case(
            "M014",
            "src/odd target [x].txt",
            "SAFE",
            "BROKEN",
            7,
            ["bash", "scripts/bsd-wc-probe.sh"],
        )

        result = self.run_harness(
            env={"PATH": str(tool_bin) + os.pathsep + os.environ["PATH"]}
        )
        self.assertEqual(result.returncode, 0, self.combined(result))
        self.assertEqual(self.target.read_bytes(), original)

    def test_surviving_mutant_fails_and_restores(self) -> None:
        original = self.write_target()
        self.set_case(
            "M002",
            "src/odd target [x].txt",
            "SAFE",
            "BROKEN",
            7,
            ["bash", "-c", "exit 0"],
        )
        result = self.run_harness()
        output = self.combined(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("code=mutant-survived", output)
        self.assertEqual(self.target.read_bytes(), original)

    def test_zero_and_multiple_replacements_fail_before_test_command(self) -> None:
        marker = self.repo / "test-command-ran"
        self.write_script("marker.sh", f": > {shlex.quote(str(marker))}\nexit 0\n")
        fixtures = ((b"NO_MATCH\n", "SAFE"), (b"SAFE then SAFE\n", "SAFE"))
        for content, before in fixtures:
            with self.subTest(content=content):
                self.write_target(content)
                marker.unlink(missing_ok=True)
                self.set_case(
                    "M003",
                    "src/odd target [x].txt",
                    before,
                    "BROKEN",
                    7,
                    ["bash", "scripts/marker.sh"],
                )
                result = self.run_harness()
                output = self.combined(result)
                self.assertEqual(result.returncode, 2, output)
                self.assertIn("code=mutation-cardinality", output)
                self.assertFalse(marker.exists())
                self.assertEqual(self.target.read_bytes(), content)

    def test_baseline_and_unexpected_mutant_outcomes_are_errors(self) -> None:
        original = self.write_target()
        self.write_script(
            "outcome.sh",
            """
if grep -a -q BROKEN 'src/odd target [x].txt'; then exit "${MUTANT_EXIT:-8}"; fi
exit "${BASELINE_EXIT:-0}"
""",
        )
        cases = (
            ({"BASELINE_EXIT": "9"}, "baseline-red"),
            ({"MUTANT_EXIT": "8"}, "mutant-outcome"),
            ({"MUTANT_EXIT": "7"}, "mutant-evidence"),
        )
        for extra_env, code in cases:
            with self.subTest(code=code):
                self.target.write_bytes(original)
                self.set_case(
                    "M004",
                    "src/odd target [x].txt",
                    "SAFE",
                    "BROKEN",
                    7,
                    ["bash", "scripts/outcome.sh"],
                )
                result = self.run_harness(env=extra_env)
                output = self.combined(result)
                self.assertEqual(result.returncode, 2, output)
                self.assertIn(f"code={code}", output)
                self.assertEqual(self.target.read_bytes(), original)

        self.set_case(
            "M005",
            "src/odd target [x].txt",
            "SAFE",
            "BROKEN",
            7,
            ["definitely-missing-mutation-command"],
        )
        missing = self.run_harness()
        self.assertEqual(missing.returncode, 2, self.combined(missing))
        self.assertIn("code=baseline-red", self.combined(missing))
        self.assertNotIn("definitely-missing", self.combined(missing))
        self.assertEqual(self.target.read_bytes(), original)

    def test_escape_symlink_and_hardlink_targets_are_rejected(self) -> None:
        original = self.write_target()
        outside = Path(self.tempdir.name) / "outside.txt"
        outside.write_bytes(b"outside sentinel\n")
        parent_link = self.repo / "linked-parent"
        os.symlink(outside.parent, parent_link)
        leaf_link = self.repo / "leaf-link.txt"
        os.symlink(outside, leaf_link)
        hardlink = self.repo / "hardlink.txt"
        os.link(self.target, hardlink)
        candidates = (
            str(outside),
            "../outside.txt",
            "leaf-link.txt",
            "linked-parent/outside.txt",
            "hardlink.txt",
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                self.set_case("M006", candidate, "outside", "BROKEN", 7, ["bash", "-c", "exit 0"])
                result = self.run_harness()
                output = self.combined(result)
                self.assertEqual(result.returncode, 2, output)
                self.assertIn("code=unsafe-target" if candidate != "hardlink.txt" else "code=target-links", output)
                self.assertNotIn(candidate, output)
                self.assertEqual(outside.read_bytes(), b"outside sentinel\n")
                self.assertEqual(self.target.read_bytes(), original)

    def test_signal_stops_process_group_and_restores(self) -> None:
        original = self.write_target()
        child_pid_file = self.repo / "child.pid"
        self.write_script(
            "signal-probe.sh",
            """
if grep -a -q BROKEN 'src/odd target [x].txt'; then
  sleep 60 &
  printf '%s\\n' "$!" > child.pid
  kill -TERM "$MUTATION_CHECK_HARNESS_PID"
  wait
fi
exit 0
""",
        )
        self.set_case(
            "M007",
            "src/odd target [x].txt",
            "SAFE",
            "BROKEN",
            7,
            ["bash", "scripts/signal-probe.sh"],
        )
        result = self.run_harness(timeout=12)
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertNotIn("mutation-check: PASS", output)
        self.assertEqual(self.target.read_bytes(), original)
        self.assertFalse((self.repo / ".mutation-check.lock").exists())
        if child_pid_file.exists():
            child_pid = int(child_pid_file.read_text().strip())
            for _ in range(40):
                proc_stat = Path(f"/proc/{child_pid}/stat")
                if proc_stat.exists() and proc_stat.read_text().split()[2] == "Z":
                    break
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail("mutant test descendant survived harness termination")

    def test_timeout_is_error_and_restores(self) -> None:
        original = self.write_target()
        self.write_script(
            "timeout-probe.sh",
            """
if grep -a -q BROKEN 'src/odd target [x].txt'; then sleep 60; fi
exit 0
""",
        )
        self.set_case(
            "M008",
            "src/odd target [x].txt",
            "SAFE",
            "BROKEN",
            7,
            ["bash", "scripts/timeout-probe.sh"],
        )
        started = time.monotonic()
        result = self.run_harness(env={"MUTATION_TIMEOUT_SECONDS": "1"}, timeout=10)
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("code=mutant-outcome", output)
        self.assertLess(time.monotonic() - started, 7)
        self.assertEqual(self.target.read_bytes(), original)

    def test_concurrent_run_is_rejected_before_mutation(self) -> None:
        original = self.write_target()
        ready = self.repo / "baseline.ready"
        self.write_script(
            "hold-probe.sh",
            """
if grep -a -q SAFE 'src/odd target [x].txt'; then
  : > baseline.ready
  sleep 2
  exit 0
fi
printf '%s\\n' "$MUTATION_CHECK_EVIDENCE_MARKER" > "$MUTATION_CHECK_EVIDENCE_FILE"
exit 7
""",
        )
        self.set_case(
            "M009",
            "src/odd target [x].txt",
            "SAFE",
            "BROKEN",
            7,
            ["bash", "scripts/hold-probe.sh"],
        )
        first = subprocess.Popen(
            [BASH, str(self.repo / "scripts" / "mutation-check.sh")],
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(lambda: first.poll() is None and first.kill())
        for _ in range(100):
            if ready.exists():
                break
            self.assertIsNone(first.poll(), "first harness exited before holding the lock")
            time.sleep(0.03)
        else:
            self.fail("first harness never reached its baseline")

        second = self.run_harness()
        self.assertEqual(second.returncode, 2, self.combined(second))
        self.assertIn("code=runtime-init", self.combined(second))
        stdout, stderr = first.communicate(timeout=10)
        self.assertEqual(first.returncode, 0, stdout + stderr)
        self.assertEqual(self.target.read_bytes(), original)

    def test_unrecognized_source_drift_preserves_both_versions(self) -> None:
        original = self.write_target()
        self.write_script(
            "drift-probe.sh",
            """
if grep -a -q BROKEN 'src/odd target [x].txt'; then
  printf '%s\\n' THIRD_STATE > 'src/odd target [x].txt'
  exit 7
fi
exit 0
""",
        )
        self.set_case(
            "M010",
            "src/odd target [x].txt",
            "SAFE",
            "BROKEN",
            7,
            ["bash", "scripts/drift-probe.sh"],
        )
        result = self.run_harness()
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("code=test-mutated-target", output)
        lock = self.repo / ".mutation-check.lock"
        self.assertTrue(lock.is_dir())
        self.assertEqual((lock / "state").read_text().strip(), "drift")
        self.assertEqual((lock / "original").read_bytes(), original)
        self.assertEqual(self.target.read_bytes(), b"THIRD_STATE\n")

    def test_stale_journal_restores_only_the_recorded_mutant(self) -> None:
        original = self.write_target()
        ready = self.repo / "mutant.ready"
        self.write_script(
            "crash-probe.sh",
            """
if grep -a -q BROKEN 'src/odd target [x].txt'; then
  : > mutant.ready
  sleep 60
  exit 7
fi
exit 0
""",
        )
        self.set_case(
            "M011",
            "src/odd target [x].txt",
            "SAFE",
            "BROKEN",
            7,
            ["bash", "scripts/crash-probe.sh"],
        )
        process = subprocess.Popen(
            [BASH, str(self.repo / "scripts" / "mutation-check.sh")],
            cwd=self.repo,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(150):
            if ready.exists():
                break
            self.assertIsNone(process.poll(), "harness exited before mutant was active")
            time.sleep(0.03)
        else:
            process.kill()
            self.fail("mutant never became active")
        process.kill()
        process.wait(timeout=5)
        lock = self.repo / ".mutation-check.lock"
        child_pgid = int((lock / "child_pgid").read_text().strip())
        try:
            os.killpg(child_pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for _ in range(40):
            try:
                os.killpg(child_pgid, 0)
            except (ProcessLookupError, PermissionError):
                break
            time.sleep(0.05)
        (lock / "child_pgid").unlink(missing_ok=True)

        self.write_script(
            "probe-after-crash.sh",
            """
if grep -a -q BROKEN 'src/odd target [x].txt'; then
  printf '%s\\n' "$MUTATION_CHECK_EVIDENCE_MARKER" > "$MUTATION_CHECK_EVIDENCE_FILE"
  exit 7
fi
exit 0
""",
        )
        self.set_case(
            "M012",
            "src/odd target [x].txt",
            "SAFE",
            "BROKEN",
            7,
            ["bash", "scripts/probe-after-crash.sh"],
        )
        recovered = self.run_harness(timeout=12)
        self.assertEqual(recovered.returncode, 0, self.combined(recovered))
        self.assertEqual(self.target.read_bytes(), original)
        self.assertFalse(lock.exists())

    def test_empty_plan_recovers_a_stale_mutant_instead_of_skipping_it(self) -> None:
        original = self.write_target()
        mutated = original.replace(b"SAFE", b"BROKEN")
        self.target.write_bytes(mutated)
        lock = self.repo / ".mutation-check.lock"
        lock.mkdir()
        (lock / "owner").write_text("99999999\n", encoding="ascii")
        (lock / "state").write_text("mutated\n", encoding="ascii")
        (lock / "target").write_text("src/odd target [x].txt\n", encoding="utf-8")
        (lock / "original").write_bytes(original)
        (lock / "original_hash").write_text(
            hashlib.sha256(original).hexdigest() + "\n", encoding="ascii"
        )
        (lock / "mutated_hash").write_text(
            hashlib.sha256(mutated).hexdigest() + "\n", encoding="ascii"
        )

        result = self.run_harness()
        self.assertEqual(result.returncode, 0, self.combined(result))
        self.assertIn("mutation-check: SKIP cases=0 configured=0", self.combined(result))
        self.assertEqual(self.target.read_bytes(), original)
        self.assertFalse(lock.exists())

    def test_drift_then_delete_remains_manual_recovery(self) -> None:
        original = self.write_target()
        mutated = original.replace(b"SAFE", b"BROKEN")
        lock = self.repo / ".mutation-check.lock"
        lock.mkdir()
        (lock / "owner").write_text("99999999\n", encoding="ascii")
        (lock / "state").write_text("drift\n", encoding="ascii")
        (lock / "target").write_text("src/odd target [x].txt\n", encoding="utf-8")
        (lock / "original").write_bytes(original)
        (lock / "original_hash").write_text(
            hashlib.sha256(original).hexdigest() + "\n", encoding="ascii"
        )
        (lock / "mutated_hash").write_text(
            hashlib.sha256(mutated).hexdigest() + "\n", encoding="ascii"
        )
        self.target.unlink()

        result = self.run_harness()
        self.assertEqual(result.returncode, 2, self.combined(result))
        self.assertIn("code=recovery-required", self.combined(result))
        self.assertFalse(self.target.exists())
        self.assertEqual((lock / "original").read_bytes(), original)

    def test_expected_exit_with_surviving_descendant_is_error(self) -> None:
        original = self.write_target()
        child_pid_file = self.repo / "survivor.pid"
        self.write_script(
            "survivor-probe.sh",
            """
if grep -a -q BROKEN 'src/odd target [x].txt'; then
  sleep 60 &
  printf '%s\\n' "$!" > survivor.pid
  printf '%s\\n' "$MUTATION_CHECK_EVIDENCE_MARKER" > "$MUTATION_CHECK_EVIDENCE_FILE"
  exit 7
fi
exit 0
""",
        )
        self.set_case(
            "M013",
            "src/odd target [x].txt",
            "SAFE",
            "BROKEN",
            7,
            ["bash", "scripts/survivor-probe.sh"],
        )

        result = self.run_harness(timeout=12)
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("code=mutant-outcome", output)
        self.assertNotIn("mutation-check: PASS", output)
        self.assertEqual(self.target.read_bytes(), original)
        self.assertFalse((self.repo / ".mutation-check.lock").exists())
        if child_pid_file.exists():
            child_pid = int(child_pid_file.read_text().strip())
            for _ in range(40):
                proc_stat = Path(f"/proc/{child_pid}/stat")
                if proc_stat.exists() and proc_stat.read_text().split()[2] == "Z":
                    break
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail("background descendant survived a reported result")

    def test_declared_stacks_expose_only_the_optional_target(self) -> None:
        config = json.loads((ROOT / "firestarter.config.json").read_text(encoding="utf-8"))
        declared = set(config["stack"])
        examples = {
            path.name.removesuffix(".answers.json")
            for path in (ROOT / "examples").glob("*.answers.json")
        }
        self.assertEqual(declared, examples)
        for stack in sorted(declared):
            makefile = (ROOT / "stacks" / stack / "Makefile").read_text(encoding="utf-8")
            self.assertIn("mutation-check:", makefile)
            self.assertIn("\n\t@bash scripts/mutation-check.sh\n", makefile)
            self.assertNotRegex(makefile, r"(?m)^test:.*mutation-check")
            self.assertNotRegex(makefile, r"(?m)^precommit:.*mutation-check")
        self.assertNotIn("perl", SCRIPT.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
