"""Adversarial contract for the optional bounded-execution runner."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addons" / "bounded_runner" / "common"
MODULE = "tools.bounded_runner"


def base_unit(**changes: object) -> dict[str, object]:
    unit: dict[str, object] = {
        "id": "unit",
        "cmd": [sys.executable, "-c", "print('ok')"],
        "cwd": ".",
        "write_paths": ["work"],
        "deadline_s": 3,
        "grace_s": 0.2,
        "workers": 1,
        "required": True,
    }
    unit.update(changes)
    return unit


def write_spec(root: Path, *, name: str = "contract", state: str = ".state",
               units: list[dict[str, object]] | None = None,
               marker: bool = True,
               **run_changes: object) -> Path:
    if marker:
        (root / ".bounded-runner-root").write_text(
            "bounded-runner-root-v1\n", encoding="utf-8"
        )
    run: dict[str, object] = {
        "name": name,
        "root": ".",
        "state": state,
        "worker_budget": 2,
        "poll_interval_s": 0.02,
    }
    run.update(run_changes)
    path = root / f"{name}.json"
    path.write_text(json.dumps({"run": run, "unit": units or [base_unit()]}), encoding="utf-8")
    return path


def runner_env(**extra: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ADDON)
    env.update(extra)
    return env


def run_cli(command: str, spec: Path, *args: str,
            env: dict[str, str] | None = None, timeout: float = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", "-m", MODULE, command, str(spec), *args],
        cwd=ROOT, env=env or runner_env(), capture_output=True, text=True, timeout=timeout,
    )


def record(root: Path, state: str, run_name: str, unit_id: str = "unit") -> dict[str, object]:
    path = root / state / "runs" / run_name / "units" / f"{unit_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


@unittest.skipUnless(os.name == "posix", "execution contract requires POSIX process groups")
class BoundedRunnerProcessContract(unittest.TestCase):
    def test_ok_and_missing_are_explicit_and_status_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec = write_spec(root)

            status = run_cli("status", spec)
            self.assertEqual(status.returncode, 1)
            self.assertIn("MISSING", status.stdout)
            self.assertFalse((root / ".state").exists(), "status must not create state")

            result = run_cli("run", spec)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(record(root, ".state", "contract")["status"], "OK")
            for private in (
                root / ".state",
                root / ".state" / "runs",
                root / ".state" / "runs" / "contract",
                root / ".state" / "runs" / "contract" / "units",
                root / ".state" / "runs" / "contract" / "logs",
                root / ".state" / "runs" / "contract" / "heartbeats",
                root / ".bounded-runner-locks",
                root / ".bounded-runner-locks" / "runs",
            ):
                self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o700, private)

    def test_deadline_kills_and_reaps_the_process_group(self) -> None:
        code = r"""
from pathlib import Path
import signal, subprocess, sys, time
Path('work').mkdir(exist_ok=True)
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
Path('work/child.pid').write_text(str(child.pid))
def stop(_signum, _frame):
    try: child.wait(timeout=2)
    except subprocess.TimeoutExpired: pass
    raise SystemExit(143)
signal.signal(signal.SIGTERM, stop)
while True: time.sleep(0.05)
"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec = write_spec(root, units=[base_unit(
                cmd=[sys.executable, "-c", code], deadline_s=0.3, grace_s=0.5,
            )])
            result = run_cli("run", spec)
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            outcome = record(root, ".state", "contract")
            self.assertEqual(outcome["status"], "TIMEOUT")
            child_pid = int((root / "work" / "child.pid").read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
            self.assertEqual(list((root / ".bounded-runner-locks").glob("*.json")), [])

    def test_stale_heartbeat_is_stalled_not_success(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec = write_spec(root, units=[base_unit(
                cmd=[sys.executable, "-c", "import time; time.sleep(5)"],
                heartbeat_stall_s=0.2,
            )])
            result = run_cli("run", spec)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(record(root, ".state", "contract")["status"], "STALLED")

    def test_resume_requires_exact_fingerprint_bound_evidence(self) -> None:
        code = r"""
from pathlib import Path
import json, os
work = Path('work'); work.mkdir(exist_ok=True)
counter = work / 'counter'
counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else '1')
checkpoint = Path(os.environ['RUNNER_CHECKPOINT'])
tmp = checkpoint.with_suffix('.tmp')
tmp.write_text(json.dumps({'runner_fingerprint': os.environ['RUNNER_FINGERPRINT'], 'done': True}))
os.replace(tmp, checkpoint)
"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec = write_spec(root, units=[base_unit(
                cmd=[sys.executable, "-c", code], checkpoint="work/checkpoint.json",
            )])
            first = run_cli("run", spec)
            self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
            unit_record = root / ".state" / "runs" / "contract" / "units" / "unit.json"
            unit_record.unlink()

            resumed = run_cli("run", spec, "--resume")
            self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
            self.assertEqual(record(root, ".state", "contract")["status"], "SKIPPED")
            self.assertEqual((root / "work" / "counter").read_text(), "1")

            payload = json.loads(spec.read_text())
            (root / "work" / "checkpoint.json").unlink()
            rerun = run_cli("run", spec, "--resume")
            self.assertEqual(rerun.returncode, 0, rerun.stderr + rerun.stdout)
            self.assertEqual(record(root, ".state", "contract")["status"], "OK")
            self.assertEqual((root / "work" / "counter").read_text(), "2")

            payload["unit"][0]["note"] = "fingerprint changes even for trusted metadata"
            spec.write_text(json.dumps(payload), encoding="utf-8")
            changed = run_cli("run", spec, "--resume")
            self.assertEqual(changed.returncode, 0, changed.stderr + changed.stdout)
            self.assertEqual(record(root, ".state", "contract")["status"], "OK")
            self.assertEqual((root / "work" / "counter").read_text(), "3")

    def test_cross_run_path_collision_is_blocked(self) -> None:
        wait_code = r"""
from pathlib import Path
import time
Path('shared').mkdir(exist_ok=True)
Path('shared/started').write_text('yes')
while not Path('release').exists(): time.sleep(0.02)
"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec_a = write_spec(
                root, name="first", state=".state-a",
                units=[base_unit(cmd=[sys.executable, "-c", wait_code], write_paths=["shared"])],
            )
            spec_b = write_spec(
                root, name="second", state=".state-b",
                units=[base_unit(write_paths=["shared"])],
            )
            first = subprocess.Popen(
                [sys.executable, "-B", "-m", MODULE, "run", str(spec_a)],
                cwd=ROOT, env=runner_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                deadline = time.monotonic() + 5
                while not (root / "shared" / "started").exists():
                    if time.monotonic() >= deadline:
                        self.fail("first runner did not acquire its unit")
                    time.sleep(0.02)
                second = run_cli("run", spec_b)
                self.assertEqual(second.returncode, 1, second.stderr + second.stdout)
                self.assertEqual(record(root, ".state-b", "second")["status"], "BLOCKED")
            finally:
                (root / "release").touch()
                stdout, stderr = first.communicate(timeout=10)
            self.assertEqual(first.returncode, 0, stderr + stdout)

    def test_same_run_concurrency_cannot_overwrite_canonical_records(self) -> None:
        wait_code = r"""
from pathlib import Path
import time
Path('work').mkdir(exist_ok=True)
Path('work/started').write_text('yes')
while not Path('release').exists(): time.sleep(0.02)
"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec = write_spec(root, units=[base_unit(cmd=[sys.executable, "-c", wait_code])])
            first = subprocess.Popen(
                [sys.executable, "-B", "-m", MODULE, "run", str(spec)],
                cwd=ROOT, env=runner_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                deadline = time.monotonic() + 5
                while not (root / "work" / "started").exists():
                    if time.monotonic() >= deadline:
                        self.fail("first runner did not start")
                    time.sleep(0.02)
                before_duplicate = record(root, ".state", "contract")
                duplicate = run_cli("run", spec)
                self.assertEqual(duplicate.returncode, 1)
                self.assertIn("run lease", duplicate.stderr)
                self.assertEqual(record(root, ".state", "contract"), before_duplicate)
            finally:
                (root / "release").touch()
                stdout, stderr = first.communicate(timeout=10)
            self.assertEqual(first.returncode, 0, stderr + stdout)
            self.assertEqual(record(root, ".state", "contract")["status"], "OK")

    def test_hard_crash_cannot_leave_an_old_success_current(self) -> None:
        code = r"""
from pathlib import Path
import time
Path('work').mkdir(exist_ok=True)
if Path('long').exists():
    Path('work/started').write_text('yes')
    time.sleep(30)
"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec = write_spec(root, units=[base_unit(
                cmd=[sys.executable, "-c", code], required=False,
            )])
            self.assertEqual(run_cli("run", spec).returncode, 0)
            (root / "long").touch()
            crashed = subprocess.Popen(
                [sys.executable, "-B", "-m", MODULE, "run", str(spec)],
                cwd=ROOT, env=runner_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            deadline = time.monotonic() + 5
            while not (root / "work" / "started").exists():
                if time.monotonic() >= deadline:
                    crashed.kill()
                    self.fail("crash fixture did not start")
                time.sleep(0.02)
            os.kill(crashed.pid, signal.SIGKILL)
            crashed.communicate(timeout=5)
            status = run_cli("status", spec)
            self.assertEqual(status.returncode, 1)
            self.assertIn("PENDING", status.stdout)
            lock = next((root / ".bounded-runner-locks").glob("*.json"))
            child_pid = int(json.loads(lock.read_text())["child_pid"])
            os.killpg(child_pid, signal.SIGKILL)
            deadline = time.monotonic() + 3
            while deadline > time.monotonic():
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.02)
            lock.unlink()
            shutil.rmtree(root / ".bounded-runner-locks" / "runs" / "contract")
            recovered_status = run_cli("status", spec)
            self.assertEqual(recovered_status.returncode, 1)
            self.assertIn("PENDING", recovered_status.stdout)

    def test_stale_lock_is_never_reaped_automatically(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            lock_root = root / ".bounded-runner-locks"
            lock_root.mkdir(mode=0o700)
            lock = lock_root / "stale.json"
            lock.write_text(json.dumps({
                "schema": 1, "instance": "old", "run": "old", "unit": "unit",
                "host": socket.gethostname(), "runner_pid": 99999999,
                "child_pid": None, "owns": [str((root / "work").resolve())],
                "started_at": "2026-01-01T00:00:00+00:00",
            }), encoding="utf-8")
            lock.chmod(0o600)
            spec = write_spec(root)
            result = run_cli("run", spec)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(record(root, ".state", "contract")["status"], "BLOCKED")
            self.assertTrue(lock.exists(), "stale lock removal requires manual process-tree proof")

    def test_interrupt_records_active_and_pending_units_killed(self) -> None:
        first_code = (
            "from pathlib import Path; import time; "
            "Path('first').mkdir(exist_ok=True); Path('first/started').write_text('yes'); "
            "time.sleep(30)"
        )
        second_code = "from pathlib import Path; Path('second').mkdir(); Path('second/ran').touch()"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec = write_spec(
                root, worker_budget=1,
                units=[
                    base_unit(id="first", cmd=[sys.executable, "-c", first_code],
                              write_paths=["first"]),
                    base_unit(id="second", cmd=[sys.executable, "-c", second_code],
                              write_paths=["second"]),
                ],
            )
            process = subprocess.Popen(
                [sys.executable, "-B", "-m", MODULE, "run", str(spec)],
                cwd=ROOT, env=runner_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            deadline = time.monotonic() + 5
            while not (root / "first" / "started").exists():
                if time.monotonic() >= deadline:
                    process.kill()
                    self.fail("active unit did not start")
                time.sleep(0.02)
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 1, stderr + stdout)
            self.assertEqual(record(root, ".state", "contract", "first")["status"], "KILLED")
            self.assertEqual(record(root, ".state", "contract", "second")["status"], "KILLED")
            self.assertFalse((root / "second" / "ran").exists())

    def test_child_environment_is_allowlisted_and_records_omit_values(self) -> None:
        code = (
            "from pathlib import Path; import json, os; Path('work').mkdir(exist_ok=True); "
            "Path('work/env.json').write_text(json.dumps(dict(os.environ)))"
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec = write_spec(root, units=[base_unit(
                cmd=[sys.executable, "-c", code],
                env={"PUBLIC_FLAG": "literal"}, inherit_env=["INHERITED_SAFE"],
                input_revision="safe-input-v1",
            )])
            result = run_cli(
                "run", spec,
                env=runner_env(INHERITED_SAFE="allowed", SECRET_SHOULD_NOT_PASS="private-value"),
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            child_env = json.loads((root / "work" / "env.json").read_text())
            self.assertEqual(child_env["INHERITED_SAFE"], "allowed")
            self.assertEqual(child_env["PUBLIC_FLAG"], "literal")
            self.assertNotIn("SECRET_SHOULD_NOT_PASS", child_env)
            outcome = record(root, ".state", "contract")
            serialized = json.dumps(outcome)
            self.assertNotIn("allowed", serialized)
            self.assertNotIn("literal", serialized)

    def test_failed_verification_cannot_report_ok(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec = write_spec(root, units=[base_unit(
                verify=[sys.executable, "-c", "raise SystemExit(7)"],
                verify_deadline_s=1,
            )])
            result = run_cli("run", spec)
            self.assertEqual(result.returncode, 1)
            outcome = record(root, ".state", "contract")
            self.assertEqual(outcome["status"], "FAIL")
            self.assertIn("verify exited 7", outcome["reason"])

    def test_zero_exit_with_surviving_descendants_is_failure(self) -> None:
        spawn_code = (
            "import subprocess, sys; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])"
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec = write_spec(root, units=[base_unit(
                cmd=[sys.executable, "-c", spawn_code], grace_s=0.2,
            )])
            result = run_cli("run", spec)
            self.assertEqual(result.returncode, 1)
            outcome = record(root, ".state", "contract")
            self.assertEqual(outcome["status"], "FAIL")
            self.assertIn("surviving process-group members", outcome["reason"])

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec = write_spec(root, units=[base_unit(
                verify=[sys.executable, "-c", spawn_code], grace_s=0.2,
            )])
            result = run_cli("run", spec)
            self.assertEqual(result.returncode, 1)
            outcome = record(root, ".state", "contract")
            self.assertEqual(outcome["status"], "FAIL")
            self.assertIn("surviving process-group members", outcome["reason"])

    def test_verification_shares_deadline_interrupt_and_lock_identity(self) -> None:
        verify_code = (
            "from pathlib import Path; import os, time; Path('work').mkdir(exist_ok=True); "
            "Path('work/verify.pid').write_text(str(os.getpid())); time.sleep(30)"
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec = write_spec(root, units=[base_unit(
                deadline_s=5, verify=[sys.executable, "-c", verify_code],
                verify_deadline_s=4,
            )])
            process = subprocess.Popen(
                [sys.executable, "-B", "-m", MODULE, "run", str(spec)],
                cwd=ROOT, env=runner_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            deadline = time.monotonic() + 5
            while not (root / "work" / "verify.pid").exists():
                if time.monotonic() >= deadline:
                    process.kill()
                    self.fail("verifier did not start")
                time.sleep(0.02)
            verify_pid = int((root / "work" / "verify.pid").read_text())
            lock = next((root / ".bounded-runner-locks").glob("*.json"))
            self.assertEqual(json.loads(lock.read_text())["child_pid"], verify_pid)
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 1, stderr + stdout)
            self.assertEqual(record(root, ".state", "contract")["status"], "KILLED")
            with self.assertRaises(ProcessLookupError):
                os.kill(verify_pid, 0)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec = write_spec(root, units=[base_unit(
                deadline_s=0.25,
                verify=[sys.executable, "-c", "import time; time.sleep(2)"],
                verify_deadline_s=1.5,
            )])
            started = time.monotonic()
            result = run_cli("run", spec)
            elapsed = time.monotonic() - started
            self.assertEqual(result.returncode, 1)
            self.assertEqual(record(root, ".state", "contract")["status"], "TIMEOUT")
            self.assertLess(elapsed, 1.25, "verification must share the unit wall-clock deadline")


class BoundedRunnerStaticContract(unittest.TestCase):
    def test_closed_schema_rejects_shells_escapes_globs_overlap_and_unknowns(self) -> None:
        invalid_units = {
            "shell string": [base_unit(cmd="echo unsafe")],
            "escape": [base_unit(write_paths=["../outside"])],
            "glob": [base_unit(write_paths=["build/*"])],
            "overlap": [base_unit(id="a"), base_unit(id="b", write_paths=["work/nested"])],
            "unknown": [base_unit(mystery=True)],
            "inherited input without revision": [base_unit(inherit_env=["INPUT_REV"])],
        }
        for label, units in invalid_units.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                spec = write_spec(root, units=units)
                result = run_cli("preflight", spec)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertFalse((root / ".state").exists())
                self.assertFalse((root / ".bounded-runner-locks").exists())

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            nested = root / "nested"
            nested.mkdir()
            (root / ".bounded-runner-root").write_text("bounded-runner-root-v1\n")
            nested_spec = write_spec(nested, marker=False, units=[base_unit(write_paths=["shared"])])
            result = run_cli("preflight", nested_spec)
            self.assertEqual(result.returncode, 2)
            self.assertIn("canonical", result.stderr)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            alias = write_spec(root, state=".bounded-runner-locks")
            result = run_cli("preflight", alias)
            self.assertEqual(result.returncode, 2)
            self.assertIn("must not overlap", result.stderr)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec = write_spec(root)
            result = run_cli("status", spec, "--wait-for-locks", "nan")
            self.assertEqual(result.returncode, 2)

    def test_optional_missing_still_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec = write_spec(root, units=[base_unit(required=False)])
            result = run_cli("status", spec)
            self.assertEqual(result.returncode, 1)
            self.assertIn("MISSING", result.stdout)

    def test_malformed_or_public_state_fails_closed_before_execution(self) -> None:
        if os.name != "posix":
            self.skipTest("POSIX private-mode contract")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec = write_spec(root, units=[base_unit(
                cmd=[sys.executable, "-c", "from pathlib import Path; Path('ran').touch()"],
            )])
            units = root / ".state" / "runs" / "contract" / "units"
            units.mkdir(parents=True)
            bad = units / "unit.json"
            bad.write_text(json.dumps({"schema": 1, "id": "unit"}), encoding="utf-8")
            bad.chmod(0o644)
            result = run_cli("run", spec)
            self.assertEqual(result.returncode, 1)
            self.assertFalse((root / "ran").exists())

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spec = write_spec(root, units=[base_unit(
                cmd=[sys.executable, "-c", "from pathlib import Path; Path('ran').touch()"],
            )])
            lock_root = root / ".bounded-runner-locks"
            lock_root.mkdir(mode=0o700)
            malformed = lock_root / "malformed.json"
            malformed.write_text("{}", encoding="utf-8")
            malformed.chmod(0o600)
            result = run_cli("run", spec)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(record(root, ".state", "contract")["status"], "BLOCKED")
            self.assertTrue(malformed.exists())
            self.assertFalse((root / "ran").exists())

    def test_every_stack_stamps_exact_addon_and_default_stays_clean(self) -> None:
        for attributes in (ROOT / ".gitattributes", ROOT / "template" / ".gitattributes"):
            self.assertIn(".bounded-runner-root text eol=lf", attributes.read_text())
        polluted = [
            path for path in ADDON.rglob("*")
            if path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}
        ]
        self.assertEqual(polluted, [], f"generated bytecode must not become an add-on artifact: {polluted}")
        wrapper = ADDON / "scripts" / "bounded-runner.sh"
        syntax = subprocess.run(["bash", "-n", str(wrapper)], capture_output=True, text=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        wrapper_text = wrapper.read_text()
        self.assertIn("python:3.13-bookworm@sha256:", wrapper_text)
        self.assertIn("--cap-drop ALL", wrapper_text)
        self.assertIn("--security-opt no-new-privileges", wrapper_text)
        with tempfile.TemporaryDirectory() as raw:
            output_root = Path(raw)
            for answers in sorted((ROOT / "examples").glob("*.answers.json")):
                with self.subTest(answers=answers.name):
                    enabled = output_root / f"enabled-{answers.stem}"
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "bin" / "generate.py"),
                         "--values", str(answers), "--set", "include_bounded_runner=yes",
                         "--output", str(enabled)],
                        cwd=ROOT, capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                    for source in sorted(ADDON.rglob("*")):
                        if source.is_file():
                            stamped = enabled / source.relative_to(ADDON)
                            self.assertTrue(stamped.is_file(), stamped)
                            # The generator intentionally reads/writes text, so a
                            # Windows checkout's CRLF source normalizes to LF in
                            # stamped output. Compare semantic text, not host EOL.
                            self.assertEqual(
                                stamped.read_text(encoding="utf-8"),
                                source.read_text(encoding="utf-8"),
                                stamped,
                            )
                    self.assertEqual(list(enabled.rglob("__pycache__")), [])
                    compiled = subprocess.run(
                        [sys.executable, "-B", "-m", "py_compile",
                         str(enabled / "tools" / "bounded_runner" / "runner.py")],
                        capture_output=True, text=True,
                    )
                    self.assertEqual(compiled.returncode, 0, compiled.stderr)

            disabled = output_root / "disabled"
            result = subprocess.run(
                [sys.executable, str(ROOT / "bin" / "generate.py"), "--defaults",
                 "--output", str(disabled)],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertFalse((disabled / "tools" / "bounded_runner").exists())
            self.assertFalse((disabled / "docs" / "BOUNDED_RUNNER.md").exists())

    def test_public_artifacts_are_generic_and_contain_no_source_secrets(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in (ROOT / "addons" / "bounded_runner").rglob("*") if path.is_file()
        ).lower()
        for forbidden in (
            "west nile", "arbovirus", "auggiehealth", "txt.att.net",
            "cloudflare_account_id", "access-client-secret", "@gmail.com",
        ):
            self.assertNotIn(forbidden, text)

        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("tests.test_bounded_runner_contract", workflow)


if __name__ == "__main__":
    unittest.main()
