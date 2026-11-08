"""Adversarial contract for the pre-capture workstation-hygiene guard.

capture-guard.sh is the executable precondition behind FEATURE_HANDOFF.md §5:
fail closed BEFORE any host-side screenshot / computer-use capture when a
project-declared sensitive process is running, or when the workstation cannot be
enumerated at all. These cases pin the three outcomes (SKIP / PASS / BLOCK), the
fail-closed direction on every enumeration failure, that the declaration is
resolved beside the script and never from the caller's cwd, and the
privacy contract: no process name or declared pattern ever reaches the output.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "template" / "scripts" / "capture-guard.sh"
SEED = ROOT / "template" / "scripts" / "capture-guard-patterns.sh"
BASH = os.environ.get("CAPTURE_GUARD_BASH", "bash")

# A pattern a workstation might declare; it must never appear in any output.
SENTINEL = "SENSITIVE_SENTINEL_PROC"
# A process name pgrep might print on stdout; the guard discards it.
LEAK = "LEAKED_PROC_NAME_8f3a2b"


class CaptureGuardContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.scripts = self.root / "project" / "scripts"
        self.scripts.mkdir(parents=True)
        self.guard = self.scripts / "capture-guard.sh"
        shutil.copy2(SCRIPT, self.guard)
        self.guard.chmod(0o755)

        self.bash = shutil.which(BASH) or BASH
        self.tool_bin = self.root / "tool-bin"
        self.tool_bin.mkdir()
        self.pgrep_log = self.root / "pgrep.log"

    # -- helpers ---------------------------------------------------------

    @property
    def patterns(self) -> Path:
        return self.scripts / "capture-guard-patterns.sh"

    def write_patterns(self, body: str) -> None:
        self.patterns.write_text(body, encoding="utf-8")

    def write_fake_pgrep(self) -> None:
        # The guard's positive control probes a universally-present process with
        # ".". A healthy enumerator (the default here) matches it; set
        # FAKE_PGREP_CONTROL_RC to model a pgrep that is present but broken.
        fake = self.tool_bin / "pgrep"
        fake.write_text(
            "#!/bin/sh\n"
            'printf "%s\\n" "$*" >> "$FAKE_PGREP_LOG"\n'
            'if [ "$1" = "." ]; then exit "${FAKE_PGREP_CONTROL_RC:-0}"; fi\n'
            'if [ -n "${FAKE_PGREP_STDOUT:-}" ]; then printf "%s\\n" "$FAKE_PGREP_STDOUT"; fi\n'
            'exit "${FAKE_PGREP_RC:-1}"\n',
            encoding="utf-8",
        )
        fake.chmod(0o755)

    def environment(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = {
            **os.environ,
            "PATH": str(self.tool_bin) + os.pathsep + os.environ["PATH"],
            "FAKE_PGREP_LOG": str(self.pgrep_log),
        }
        env.update(extra or {})
        return env

    def run_guard(
        self,
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [self.bash, str(self.guard)],
            cwd=str(cwd or self.scripts),
            env=self.environment(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=15,
        )

    @staticmethod
    def combined(result: subprocess.CompletedProcess[bytes]) -> str:
        return (result.stdout + result.stderr).decode("utf-8", errors="replace")

    # -- the three outcomes ---------------------------------------------

    def test_shipped_empty_seed_is_a_truthful_skip(self) -> None:
        """The file firestarter actually stamps declares nothing -> SKIP, not a pass."""
        shutil.copy2(SEED, self.patterns)
        self.write_fake_pgrep()
        result = self.run_guard(env={"FAKE_PGREP_RC": "0"})
        output = self.combined(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("SKIP patterns=0", output)
        # A SKIP must not have enumerated: no pattern was declared to check.
        self.assertFalse(self.pgrep_log.exists(), output)

    def test_declared_process_absent_passes(self) -> None:
        self.write_patterns(f'capture_pattern "{SENTINEL}"\n')
        self.write_fake_pgrep()
        result = self.run_guard(env={"FAKE_PGREP_RC": "1"})
        output = self.combined(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("PASS patterns=1 matched=0", output)
        self.assertNotIn(SENTINEL, output)

    def test_declared_sensitive_process_running_blocks(self) -> None:
        self.write_patterns(f'capture_pattern "{SENTINEL}"\n')
        self.write_fake_pgrep()
        result = self.run_guard(env={"FAKE_PGREP_RC": "0"})
        output = self.combined(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("BLOCK", output)
        self.assertIn("matched_patterns=1", output)
        self.assertNotIn(SENTINEL, output)

    # -- fail-closed on every enumeration failure -----------------------

    def test_enumerator_missing_blocks_closed(self) -> None:
        """No pgrep on PATH at all -> cannot enumerate -> BLOCK, never a silent pass."""
        self.write_patterns(f'capture_pattern "{SENTINEL}"\n')
        isolated = self.root / "isolated-bin"
        isolated.mkdir()
        dirname = shutil.which("dirname")
        self.assertIsNotNone(dirname)
        os.symlink(dirname, isolated / "dirname")
        result = subprocess.run(
            [self.bash, str(self.guard)],
            cwd=str(self.scripts),
            env={"PATH": str(isolated), "FAKE_PGREP_LOG": str(self.pgrep_log)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=15,
        )
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("enumeration-unavailable", output)
        self.assertNotIn(SENTINEL, output)

    def test_enumerator_error_blocks_closed(self) -> None:
        """pgrep present but erroring (rc neither 0 nor 1) -> BLOCK, not treated as clean."""
        self.write_patterns(f'capture_pattern "{SENTINEL}"\n')
        self.write_fake_pgrep()
        result = self.run_guard(env={"FAKE_PGREP_RC": "2"})
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("enumeration-unavailable", output)
        self.assertNotIn(SENTINEL, output)

    def test_empty_pattern_declaration_fails_closed(self) -> None:
        self.write_patterns('capture_pattern ""\n')
        self.write_fake_pgrep()
        result = self.run_guard(env={"FAKE_PGREP_RC": "1"})
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("empty-pattern", output)

    def test_flag_shaped_pattern_fails_closed(self) -> None:
        """A pattern that could be read as a pgrep flag is a bad declaration -> BLOCK."""
        self.write_patterns('capture_pattern "-x"\n')
        self.write_fake_pgrep()
        result = self.run_guard(env={"FAKE_PGREP_RC": "1"})
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("unsafe-pattern", output)
        self.assertNotIn("-x", output)

    def test_missing_patterns_file_fails_closed(self) -> None:
        self.write_fake_pgrep()
        result = self.run_guard(env={"FAKE_PGREP_RC": "0"})
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("patterns-file-missing", output)

    def test_unsourceable_patterns_file_fails_closed(self) -> None:
        # A sentinel ON the malformed line: bash's parse error would echo this
        # line, so the source-time suppression must keep the declaration content
        # out of the guard's output even when the file does not parse.
        self.write_patterns(f'capture_pattern "{SENTINEL}" )\n')  # stray token -> parse error
        self.write_fake_pgrep()
        result = self.run_guard(env={"FAKE_PGREP_RC": "1"})
        output = self.combined(result)
        self.assertEqual(result.returncode, 2, output)
        self.assertIn("patterns-source-failed", output)
        self.assertNotIn(SENTINEL, output)

    def test_broken_enumerator_reporting_no_match_blocks_closed(self) -> None:
        """A present pgrep that cannot even match a universally-present process is
        broken or lying; its "no match" must never clear a declared process to PASS."""
        self.write_patterns(f'capture_pattern "{SENTINEL}"\n')
        self.write_fake_pgrep()
        for control_rc in ("1", "2"):  # 1 = silently always "no match"; 2 = errors
            with self.subTest(control_rc=control_rc):
                result = self.run_guard(
                    env={"FAKE_PGREP_RC": "1", "FAKE_PGREP_CONTROL_RC": control_rc}
                )
                output = self.combined(result)
                self.assertEqual(result.returncode, 2, output)
                self.assertIn("enumeration-unavailable", output)
                self.assertNotIn(SENTINEL, output)
                if self.pgrep_log.exists():
                    self.pgrep_log.unlink()

    def test_whitespace_only_declaration_fails_closed(self) -> None:
        self.write_fake_pgrep()
        for label, body in (
            ("spaces", 'capture_pattern "   "\n'),
            ("tab", 'capture_pattern "\t"\n'),
            ("mixed", 'capture_pattern " \t "\n'),
        ):
            with self.subTest(case=label):
                self.write_patterns(body)
                result = self.run_guard(env={"FAKE_PGREP_RC": "1"})
                output = self.combined(result)
                self.assertEqual(result.returncode, 2, output)
                self.assertIn("empty-pattern", output)

    # -- structural safety ----------------------------------------------

    def test_patterns_resolved_beside_script_not_cwd(self) -> None:
        """A decoy declaration in the caller's cwd must not be sourced."""
        shutil.copy2(SEED, self.patterns)  # beside the script: empty -> SKIP
        self.write_fake_pgrep()
        decoy = self.root / "decoy"
        decoy.mkdir()
        (decoy / "capture-guard-patterns.sh").write_text(
            f'capture_pattern "{SENTINEL}"\n', encoding="utf-8"
        )
        result = self.run_guard(env={"FAKE_PGREP_RC": "0"}, cwd=decoy)
        output = self.combined(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("SKIP patterns=0", output)
        self.assertNotIn(SENTINEL, output)

    def test_pgrep_stdout_is_discarded_not_echoed(self) -> None:
        """Even if the enumerator prints a process name, the guard never relays it."""
        self.write_patterns(f'capture_pattern "{SENTINEL}"\n')
        self.write_fake_pgrep()
        result = self.run_guard(env={"FAKE_PGREP_RC": "0", "FAKE_PGREP_STDOUT": LEAK})
        output = self.combined(result)
        self.assertEqual(result.returncode, 1, output)
        self.assertNotIn(LEAK, output)
        self.assertNotIn(SENTINEL, output)


if __name__ == "__main__":
    unittest.main()
