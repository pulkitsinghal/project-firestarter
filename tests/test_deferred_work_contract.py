"""Adversarial contract for file-first deferred-work capture."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "template" / "scripts" / "defer-work.sh"
LEDGER = ROOT / "template" / "docs" / "DEFERRED_WORK.md"
BASH = os.environ.get("DEFER_WORK_BASH", "bash")
ID1 = "dw-0123456789abcdef"
ID2 = "dw-fedcba9876543210"


class DeferredWorkContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.repo = Path(self.tempdir.name) / "project"
        (self.repo / "scripts").mkdir(parents=True)
        (self.repo / "docs").mkdir()
        shutil.copy2(SCRIPT, self.repo / "scripts" / "defer-work.sh")
        (self.repo / "scripts" / "defer-work.sh").chmod(0o755)
        shutil.copy2(LEDGER, self.repo / "docs" / "DEFERRED_WORK.md")

        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/example/project.git"],
            cwd=self.repo,
            check=True,
        )
        subprocess.run(
            ["git", "add", "docs/DEFERRED_WORK.md", "scripts/defer-work.sh"],
            cwd=self.repo,
            check=True,
        )

        self.sentinels = (
            "SYNTHETIC_PRIVATE_SUMMARY_DO_NOT_PROJECT",
            "SYNTHETIC_PRIVATE_DEPENDENCY_DO_NOT_PROJECT",
            "SYNTHETIC_PRIVATE_COMPLETION_DO_NOT_PROJECT",
            "SYNTHETIC_PRIVATE_NOTE_DO_NOT_PROJECT",
        )
        self.secret = self.sentinels[0]
        self.payload = (
            f"Summary: {self.sentinels[0]}\n"
            "Status: deferred\n"
            f"Dependency: {self.sentinels[1]}\n"
            f"Completion test: {self.sentinels[2]}\n"
            f"Notes: {self.sentinels[3]}\n"
        ).encode("utf-8")
        self.tool_bin = Path(self.tempdir.name) / "tool-bin"
        self.tool_bin.mkdir()
        self.gh_log = Path(self.tempdir.name) / "gh.log"
        self.order_failure = Path(self.tempdir.name) / "order-failure"
        self.write_fake_gh()

    @property
    def ledger(self) -> Path:
        return self.repo / "docs" / "DEFERRED_WORK.md"

    @staticmethod
    def record_bytes(suffix: str = "", *, newline: str = "\n", final: bool = True) -> bytes:
        text = newline.join(
            [
                f"Summary: Reconcile synthetic rejects {suffix}",
                "Status: deferred",
                "Dependency: The synthetic taxonomy is approved.",
                "Completion test: The fixture imports with no parked rows.",
            ]
        )
        if final:
            text += newline
        return text.encode("utf-8")

    def write_fake_gh(self) -> None:
        path = self.tool_bin / "gh"
        path.write_text(
            f"""#!/bin/sh
set -u
if ! grep -Fq '<!-- deferred-work:v1 id={ID1} ' "$FAKE_LEDGER"; then
  printf order > "$FAKE_ORDER_FAILURE"
  exit 97
fi
printf '%s\\n' "$*" >> "$FAKE_GH_LOG"
phase=unknown
if [ "$1" = auth ]; then
  phase=auth
elif [ "$1 $2" = 'issue list' ]; then
  phase=list
elif [ "$1 $2" = 'issue create' ]; then
  phase=create
elif [ "$1 $2" = 'issue reopen' ]; then
  phase=reopen
fi
if [ "${{FAKE_GH_HANG_PHASE:-}}" = "$phase" ]; then
  printf '%s\\n' "$$" > "$FAKE_GH_HANG_PID"
  while :; do :; done
fi
if [ "$1" = auth ]; then
  [ "${{FAKE_GH_FAIL_AUTH:-0}}" != 1 ]
  exit $?
fi
if [ "$1 $2" = 'issue list' ]; then
  [ "${{FAKE_GH_FAIL_SEARCH:-0}}" != 1 ] || exit 93
  printf '%s' "${{FAKE_GH_EXISTING:-}}"
  exit 0
fi
if [ "${{FAKE_GH_FAIL_WRITE:-0}}" = 1 ]; then exit 92; fi
exit 0
""",
            encoding="utf-8",
        )
        path.chmod(0o755)

    def environment(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = {
            **os.environ,
            "PATH": str(self.tool_bin) + os.pathsep + os.environ["PATH"],
            "FAKE_LEDGER": str(self.ledger),
            "FAKE_GH_LOG": str(self.gh_log),
            "FAKE_ORDER_FAILURE": str(self.order_failure),
        }
        env.update(extra or {})
        return env

    def command(self, record_id: str = ID1, *extra: str) -> list[str]:
        return [
            BASH,
            str(self.repo / "scripts" / "defer-work.sh"),
            record_id,
            *extra,
        ]

    def run_helper(
        self,
        record_id: str = ID1,
        *extra: str,
        payload: bytes | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.command(record_id, *extra),
            cwd=self.repo,
            env=self.environment(env),
            input=payload if payload is not None else self.payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=15,
        )

    @staticmethod
    def combined(result: subprocess.CompletedProcess[str]) -> str:
        return (result.stdout + result.stderr).decode("utf-8", errors="replace")

    def test_file_is_persisted_before_content_free_issue_projection(self) -> None:
        result = self.run_helper()
        output = self.combined(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("local=created tracker=created", output)
        ledger_text = self.ledger.read_text(encoding="utf-8")
        for sentinel in self.sentinels:
            self.assertIn(sentinel, ledger_text)
        self.assertFalse(self.order_failure.exists())
        projected = self.gh_log.read_text(encoding="utf-8")
        self.assertIn("issue create", projected)
        self.assertIn("docs/DEFERRED_WORK.md", projected)
        for sentinel in self.sentinels:
            self.assertNotIn(sentinel, projected)
            self.assertNotIn(sentinel, output)

    def test_tracker_failures_are_safe_after_successful_local_write(self) -> None:
        for flag, warning in (
            ("FAKE_GH_FAIL_AUTH", "tracker-auth"),
            ("FAKE_GH_FAIL_SEARCH", "tracker-search"),
            ("FAKE_GH_FAIL_WRITE", "tracker-write"),
        ):
            with self.subTest(flag=flag):
                result = self.run_helper(env={flag: "1"})
                output = self.combined(result)
                self.assertEqual(result.returncode, 0, output)
                self.assertIn(f"WARN code={warning}", output)
                self.assertIn("tracker=pending", output)
                self.assertIn(self.secret, self.ledger.read_text(encoding="utf-8"))
                self.ledger.write_bytes(LEDGER.read_bytes())
                if self.gh_log.exists():
                    self.gh_log.unlink()

    def test_same_id_and_bytes_replay_without_duplicate_and_retry_tracking(self) -> None:
        first = self.run_helper()
        self.assertEqual(first.returncode, 0, self.combined(first))
        self.gh_log.unlink()
        second = self.run_helper(env={"FAKE_GH_EXISTING": "42\tOPEN"})
        output = self.combined(second)
        self.assertEqual(second.returncode, 0, output)
        self.assertIn("local=replayed tracker=present", output)
        self.assertEqual(self.ledger.read_text(encoding="utf-8").count(f"id={ID1} sha256="), 1)
        self.assertNotIn("issue reopen", self.gh_log.read_text(encoding="utf-8"))

    def test_exact_closed_projection_is_reopened(self) -> None:
        first = self.run_helper()
        self.assertEqual(first.returncode, 0, self.combined(first))
        self.gh_log.unlink()
        replay = self.run_helper(env={"FAKE_GH_EXISTING": "42\tCLOSED"})
        output = self.combined(replay)
        self.assertEqual(replay.returncode, 0, output)
        self.assertIn("tracker=reopened", output)
        self.assertIn("issue reopen 42", self.gh_log.read_text(encoding="utf-8"))

    def test_same_id_with_different_bytes_fails_before_tracker(self) -> None:
        first = self.run_helper()
        self.assertEqual(first.returncode, 0, self.combined(first))
        original = self.ledger.read_bytes()
        self.gh_log.unlink()
        result = self.run_helper(payload=self.record_bytes("changed"))
        self.assertEqual(result.returncode, 2, self.combined(result))
        self.assertIn("ERROR code=record-id-conflict", self.combined(result))
        self.assertEqual(self.ledger.read_bytes(), original)
        self.assertFalse(self.gh_log.exists())

    def test_crlf_and_missing_final_newline_have_one_canonical_form(self) -> None:
        crlf = self.record_bytes("canonical", newline="\r\n", final=False)
        result = self.run_helper(ID1, "--local-only", payload=crlf)
        self.assertEqual(result.returncode, 0, self.combined(result))
        ledger = self.ledger.read_bytes()
        expected = self.record_bytes("canonical", newline="\n", final=True)
        self.assertIn(expected, ledger)
        self.assertNotIn(b"\r", ledger)
        replay = self.run_helper(ID1, "--local-only", payload=expected)
        self.assertEqual(replay.returncode, 0, self.combined(replay))
        self.assertIn("local=replayed", self.combined(replay))

    def test_required_leaf_fields_fail_closed(self) -> None:
        valid_lines = [
            "Summary: Synthetic item",
            "Status: blocked",
            "Dependency: Synthetic approval.",
            "Completion test: Fixture passes.",
        ]
        for index, name in enumerate(("summary", "status", "dependency", "completion")):
            with self.subTest(field=name):
                payload = (
                    "\n".join(line for line_index, line in enumerate(valid_lines) if line_index != index)
                    + "\n"
                ).encode()
                result = self.run_helper(payload=payload)
                self.assertEqual(result.returncode, 2, self.combined(result))
                self.assertIn("ERROR code=record-schema", self.combined(result))
                self.assertNotIn(f"id={ID1} sha256=", self.ledger.read_text(encoding="utf-8"))
                self.assertFalse(self.gh_log.exists())

    def test_unsafe_input_is_rejected_without_tracker(self) -> None:
        cases = [
            ("unsafe-id", "dw-west-nile-private", self.payload),
            ("record-marker", ID1, self.record_bytes("<!-- deferred-work:x -->")),
            ("record-size", ID1, self.payload + b"x" * 65536),
            ("record-size", ID1, b""),
            ("record-control-byte", ID1, self.payload + b"\x00"),
            ("record-control-byte", ID1, self.payload + b"\x1b"),
            ("record-schema", ID1, self.payload.replace(b"Status: deferred", b"Status: parked")),
            ("record-schema", ID1, self.payload + b"Status: parked\n"),
            ("record-schema", ID1, self.payload + b"~~~text\nStatus: parked\n~~~\n"),
        ]
        for expected, record_id, payload in cases:
            with self.subTest(expected=expected):
                result = self.run_helper(record_id, payload=payload)
                self.assertEqual(result.returncode, 2, self.combined(result))
                self.assertIn(f"ERROR code={expected}", self.combined(result))
                self.assertFalse(self.gh_log.exists())

    def test_chunked_oversized_pipe_is_not_silently_truncated(self) -> None:
        process = subprocess.Popen(
            self.command(ID1, "--local-only"),
            cwd=self.repo,
            env=self.environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdin is not None
        process.stdin.write(self.payload)
        process.stdin.flush()
        time.sleep(0.1)
        try:
            process.stdin.write(b"x" * 65536)
            process.stdin.flush()
        except BrokenPipeError:
            pass
        process.stdin.close()
        status = process.wait(timeout=10)
        assert process.stdout is not None
        assert process.stderr is not None
        output = process.stdout.read() + process.stderr.read()
        process.stdout.close()
        process.stderr.close()
        self.assertEqual(status, 2, output.decode(errors="replace"))
        self.assertIn(b"ERROR code=record-size", output)
        self.assertNotIn(f"id={ID1} sha256=".encode(), self.ledger.read_bytes())
        self.assertFalse(self.gh_log.exists())

    def test_bsd_wc_count_padding_is_portable(self) -> None:
        real_wc = shutil.which("wc")
        self.assertIsNotNone(real_wc)
        fake_wc = self.tool_bin / "wc"
        fake_wc.write_text(
            "#!/bin/sh\n"
            f"count=$({shlex.quote(real_wc)} -c)\n"
            "printf '     %s\\n' \"$count\"\n",
            encoding="utf-8",
        )
        fake_wc.chmod(0o755)
        result = self.run_helper(ID1, "--local-only")
        self.assertEqual(result.returncode, 0, self.combined(result))
        self.assertIn("local=created tracker=disabled", self.combined(result))

    def test_every_tracker_phase_has_a_process_deadline(self) -> None:
        real_sleep = shutil.which("sleep")
        self.assertIsNotNone(real_sleep)
        fake_sleep = self.tool_bin / "sleep"
        fake_sleep.write_text(
            f"#!/bin/sh\nexec {shlex.quote(real_sleep)} 0.001\n",
            encoding="utf-8",
        )
        fake_sleep.chmod(0o755)
        hang_pid = Path(self.tempdir.name) / "gh-hang.pid"

        for phase, existing in (
            ("auth", ""),
            ("list", ""),
            ("create", ""),
            ("reopen", "42\tCLOSED"),
        ):
            with self.subTest(phase=phase):
                result = self.run_helper(
                    env={
                        "FAKE_GH_HANG_PHASE": phase,
                        "FAKE_GH_HANG_PID": str(hang_pid),
                        "FAKE_GH_EXISTING": existing,
                    }
                )
                output = self.combined(result)
                self.assertEqual(result.returncode, 0, output)
                self.assertIn("tracker=pending", output)
                self.assertTrue(hang_pid.exists())
                hung_pid = int(hang_pid.read_text(encoding="utf-8"))
                with self.assertRaises(ProcessLookupError):
                    os.kill(hung_pid, 0)
                self.ledger.write_bytes(LEDGER.read_bytes())
                hang_pid.unlink()
                if self.gh_log.exists():
                    self.gh_log.unlink()

    def test_existing_lock_is_never_reaped_or_tracked(self) -> None:
        lock_path = subprocess.run(
            ["git", "rev-parse", "--git-path", "defer-work.lock"],
            cwd=self.repo,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
        lock = self.repo / lock_path
        lock.mkdir()
        result = self.run_helper()
        self.assertEqual(result.returncode, 2, self.combined(result))
        self.assertIn("ERROR code=recovery-required", self.combined(result))
        self.assertTrue(lock.is_dir())
        self.assertFalse(self.gh_log.exists())

    def test_atomic_replace_failure_keeps_original_and_skips_tracker(self) -> None:
        original = self.ledger.read_bytes()
        fake_mv = self.tool_bin / "mv"
        fake_mv.write_text("#!/bin/sh\nexit 88\n", encoding="utf-8")
        fake_mv.chmod(0o755)
        result = self.run_helper()
        self.assertEqual(result.returncode, 2, self.combined(result))
        self.assertIn("ERROR code=canonical-replace", self.combined(result))
        self.assertEqual(self.ledger.read_bytes(), original)
        self.assertFalse(self.gh_log.exists())
        self.assertFalse((self.repo / ".git" / "defer-work.lock").exists())

    def test_private_temp_and_hash_failures_skip_tracker(self) -> None:
        original = self.ledger.read_bytes()
        for tool, body, expected in (
            ("mktemp", "#!/bin/sh\nexit 81\n", "private-temp-create"),
            ("sha256sum", "#!/bin/sh\nexit 82\n", "sha256-unavailable"),
        ):
            with self.subTest(tool=tool):
                fake = self.tool_bin / tool
                fake.write_text(body, encoding="utf-8")
                fake.chmod(0o755)
                result = self.run_helper()
                self.assertEqual(result.returncode, 2, self.combined(result))
                self.assertIn(f"ERROR code={expected}", self.combined(result))
                self.assertEqual(self.ledger.read_bytes(), original)
                self.assertFalse(self.gh_log.exists())
                fake.unlink()

    def test_ledger_must_be_tracked_single_link_without_symlink_components(self) -> None:
        subprocess.run(
            ["git", "rm", "--cached", "docs/DEFERRED_WORK.md"],
            cwd=self.repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        untracked = self.run_helper()
        self.assertEqual(untracked.returncode, 2, self.combined(untracked))
        self.assertIn("ERROR code=canonical-ledger", self.combined(untracked))
        subprocess.run(["git", "add", "docs/DEFERRED_WORK.md"], cwd=self.repo, check=True)

        hardlink = self.repo / "hardlink-ledger"
        try:
            os.link(self.ledger, hardlink)
        except OSError as exc:
            self.skipTest(f"hard links unavailable: {exc}")
        linked = self.run_helper()
        self.assertEqual(linked.returncode, 2, self.combined(linked))
        self.assertIn("ERROR code=canonical-ledger", self.combined(linked))
        hardlink.unlink()

        real_docs = self.repo / "real-docs"
        self.ledger.parent.rename(real_docs)
        try:
            self.ledger.parent.symlink_to(real_docs, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symlinks unavailable: {exc}")
        symlinked = self.run_helper()
        self.assertEqual(symlinked.returncode, 2, self.combined(symlinked))
        self.assertIn("ERROR code=canonical-ledger", self.combined(symlinked))
        self.assertFalse(self.gh_log.exists())

    def test_corrupt_existing_ledger_fails_closed(self) -> None:
        first = self.run_helper(ID1, "--local-only")
        self.assertEqual(first.returncode, 0, self.combined(first))
        clean = self.ledger.read_text(encoding="utf-8")
        variants = [
            clean.replace("sha256=", "sha256=x", 1),
            clean + clean[clean.index(f"<!-- deferred-work:v1 id={ID1} ") :],
            clean.replace(f"<!-- deferred-work:v1 end id={ID1} -->", "<!-- deferred-work:v1 end id=dw-aaaaaaaaaaaaaaaa -->"),
        ]
        for corrupt in variants:
            with self.subTest():
                self.ledger.write_text(corrupt, encoding="utf-8")
                result = self.run_helper(ID2, "--local-only", payload=self.record_bytes("second"))
                self.assertEqual(result.returncode, 2, self.combined(result))
                self.assertIn("ERROR code=ledger-corrupt", self.combined(result))
        self.assertFalse(self.gh_log.exists())

    def test_live_lock_contention_never_interleaves_and_retry_succeeds(self) -> None:
        real_cp = shutil.which("cp")
        self.assertIsNotNone(real_cp)
        entered = Path(self.tempdir.name) / "cp-entered"
        release = Path(self.tempdir.name) / "cp-release"
        fake_cp = self.tool_bin / "cp"
        fake_cp.write_text(
            "#!/bin/sh\n"
            'if [ "${FAKE_BLOCK_CP:-0}" = 1 ]; then\n'
            '  : > "$FAKE_CP_ENTERED"\n'
            '  while [ ! -f "$FAKE_CP_RELEASE" ]; do sleep 0.02; done\n'
            "fi\n"
            f"exec {shlex.quote(real_cp)} \"$@\"\n",
            encoding="utf-8",
        )
        fake_cp.chmod(0o755)
        blocking_env = self.environment(
            {
                "FAKE_BLOCK_CP": "1",
                "FAKE_CP_ENTERED": str(entered),
                "FAKE_CP_RELEASE": str(release),
            }
        )
        first = subprocess.Popen(
            self.command(ID1, "--local-only"),
            cwd=self.repo,
            env=blocking_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert first.stdin is not None
        first.stdin.write(self.payload)
        first.stdin.close()

        deadline = time.monotonic() + 3
        while not entered.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(entered.exists(), "first writer did not reach the locked copy")

        contender = self.run_helper(
            ID2,
            "--local-only",
            payload=self.record_bytes("second"),
            env={
                "FAKE_BLOCK_CP": "1",
                "FAKE_CP_ENTERED": str(entered),
                "FAKE_CP_RELEASE": str(release),
            },
        )
        self.assertEqual(contender.returncode, 2, self.combined(contender))
        self.assertIn("ERROR code=recovery-required", self.combined(contender))

        release.touch()
        first_status = first.wait(timeout=10)
        assert first.stdout is not None
        assert first.stderr is not None
        first_output = first.stdout.read() + first.stderr.read()
        first.stdout.close()
        first.stderr.close()
        self.assertEqual(first_status, 0, first_output.decode())
        fake_cp.unlink()
        retry = self.run_helper(ID2, "--local-only", payload=self.record_bytes("second"))
        self.assertEqual(retry.returncode, 0, self.combined(retry))
        text = self.ledger.read_text(encoding="utf-8")
        self.assertEqual(text.count(f"id={ID1} sha256="), 1)
        self.assertEqual(text.count(f"id={ID2} sha256="), 1)

    def test_local_only_never_invokes_gh(self) -> None:
        result = self.run_helper(ID1, "--local-only")
        self.assertEqual(result.returncode, 0, self.combined(result))
        self.assertIn("tracker=disabled", self.combined(result))
        self.assertFalse(self.gh_log.exists())


if __name__ == "__main__":
    unittest.main()
