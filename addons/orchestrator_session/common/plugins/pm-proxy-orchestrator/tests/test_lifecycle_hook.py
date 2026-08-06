from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_pre_tool_use_hook import invoke


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
POST = PLUGIN_ROOT / "hooks" / "post_tool_use_lifecycle.py"
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))
from post_tool_use_lifecycle import OWNER_DECISION_SINK_THREAD_ID


class LifecycleHookTest(unittest.TestCase):
    def run_post(self, home: Path, event: dict) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["HOME"] = str(home)
        env["ROOT_ORCHESTRATOR_ROLE"] = "trusted-project-hook"
        return subprocess.run(
            [sys.executable, str(POST)],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            env=env,
            check=False,
            timeout=5,
        )

    @staticmethod
    def state_root(home: Path) -> Path:
        root = home / ".codex" / "orchestrator-state"
        root.mkdir(parents=True, mode=0o700)
        os.chmod(root, 0o700)
        os.chmod(root.parent, 0o700)
        return root

    @staticmethod
    def write_ticket(
        root: Path,
        name: str,
        *,
        external_thread_id: str | None,
        malformed: bool = False,
    ) -> Path:
        state = root / "authority"
        state.mkdir(mode=0o700, exist_ok=True)
        os.chmod(state, 0o700)
        path = state / f"{name}.ticket.json"
        if malformed:
            path.write_text("{not-json\n", encoding="utf-8")
        else:
            receipt = (
                None
                if external_thread_id is None
                else {"external_thread_id": external_thread_id}
            )
            path.write_text(
                json.dumps({"receipt": receipt}, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        os.chmod(path, 0o600)
        return path

    @staticmethod
    def write_debt(root: Path, identities: list[str]) -> Path:
        path = root / ".dispatcher-lifecycle.json"
        path.write_text(
            json.dumps({"root-session": identities}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(path, 0o600)
        return path

    def test_owner_decision_sink_observations_never_create_worker_debt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pm-proxy-owner-sink-") as temp:
            home = Path(temp)
            state_root = self.state_root(home)
            pre = invoke(
                "codex_appread_thread",
                tool_input={"threadId": OWNER_DECISION_SINK_THREAD_ID},
                session_id="root-session",
                home=home,
            )
            self.assertEqual("", pre.stdout)
            post = self.run_post(
                home,
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": "root-session",
                    "tool_name": "codex_appread_thread",
                    "tool_input": {"threadId": OWNER_DECISION_SINK_THREAD_ID},
                    "tool_response": {"status": "completed"},
                },
            )
            self.assertEqual(0, post.returncode, post.stderr)
            self.assertFalse((state_root / ".dispatcher-lifecycle.json").exists())

    def test_mixed_observation_records_only_receipted_worker(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pm-proxy-owner-mixed-") as temp:
            home = Path(temp)
            state_root = self.state_root(home)
            self.write_ticket(
                state_root, "worker", external_thread_id="worker-thread"
            )
            pre = invoke(
                "codex_appwait_threads",
                tool_input={
                    "targets": [
                        {"threadId": OWNER_DECISION_SINK_THREAD_ID},
                        {"threadId": "worker-thread"},
                    ]
                },
                session_id="root-session",
                home=home,
            )
            self.assertEqual("", pre.stdout)
            ledger = json.loads(
                (state_root / ".dispatcher-lifecycle.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(["worker-thread"], ledger["root-session"])

    def test_sink_receipt_collision_and_duplicate_task_receipts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pm-proxy-owner-collision-") as temp:
            home = Path(temp)
            state_root = self.state_root(home)
            self.write_ticket(
                state_root,
                "sink-collision",
                external_thread_id=OWNER_DECISION_SINK_THREAD_ID,
            )
            sink = invoke(
                "codex_appread_thread",
                tool_input={"threadId": OWNER_DECISION_SINK_THREAD_ID},
                session_id="root-session",
                home=home,
            )
            self.assertIn("ROOT_LIFECYCLE_IDENTITY_INVALID", sink.stdout)
            self.write_ticket(
                state_root, "duplicate-one", external_thread_id="duplicate-worker"
            )
            self.write_ticket(
                state_root, "duplicate-two", external_thread_id="duplicate-worker"
            )
            duplicate = invoke(
                "codex_appread_thread",
                tool_input={"threadId": "duplicate-worker"},
                session_id="root-session",
                home=home,
            )
            self.assertIn("ROOT_LIFECYCLE_IDENTITY_INVALID", duplicate.stdout)
            self.assertFalse((state_root / ".dispatcher-lifecycle.json").exists())

    def test_legacy_sink_debt_migrates_once_after_receipt_scan(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pm-proxy-owner-migrate-") as temp:
            home = Path(temp)
            state_root = self.state_root(home)
            ledger_path = self.write_debt(
                state_root, [OWNER_DECISION_SINK_THREAD_ID]
            )
            first = invoke(
                "mcp__pm_proxy_orchestrator__pm_proxy_status",
                session_id="root-session",
                home=home,
            )
            self.assertEqual("", first.stdout)
            self.assertEqual({}, json.loads(ledger_path.read_text(encoding="utf-8")))
            migrated_stat = ledger_path.stat()
            second = invoke(
                "mcp__pm_proxy_orchestrator__pm_proxy_status",
                session_id="root-session",
                home=home,
            )
            self.assertEqual("", second.stdout)
            self.assertEqual(migrated_stat.st_ino, ledger_path.stat().st_ino)
            self.assertEqual(migrated_stat.st_mtime_ns, ledger_path.stat().st_mtime_ns)

    def test_legacy_migration_preserves_real_incomplete_and_unknown_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pm-proxy-owner-retain-") as temp:
            home = Path(temp)
            state_root = self.state_root(home)
            self.write_ticket(
                state_root, "real", external_thread_id="receipted-worker"
            )
            self.write_ticket(state_root, "incomplete", external_thread_id=None)
            ledger_path = self.write_debt(
                state_root,
                [
                    OWNER_DECISION_SINK_THREAD_ID,
                    "receipted-worker",
                    "incomplete-worker",
                    "unknown-worker",
                ],
            )
            blocked = invoke(
                "mcp__pm_proxy_orchestrator__pm_proxy_status",
                session_id="root-session",
                home=home,
            )
            self.assertIn("ROOT_LIFECYCLE_RECONCILIATION_REQUIRED", blocked.stdout)
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(
                ["receipted-worker", "incomplete-worker", "unknown-worker"],
                ledger["root-session"],
            )

    def test_legacy_migration_preserves_sink_mismatch_and_failed_verification(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="pm-proxy-owner-mismatch-") as temp:
            home = Path(temp)
            state_root = self.state_root(home)
            self.write_ticket(
                state_root,
                "sink-task",
                external_thread_id=OWNER_DECISION_SINK_THREAD_ID,
            )
            ledger_path = self.write_debt(
                state_root, [OWNER_DECISION_SINK_THREAD_ID]
            )
            mismatch = invoke(
                "mcp__pm_proxy_orchestrator__pm_proxy_status",
                session_id="root-session",
                home=home,
            )
            self.assertIn("ROOT_LIFECYCLE_RECONCILIATION_REQUIRED", mismatch.stdout)
            self.assertEqual(
                {"root-session": [OWNER_DECISION_SINK_THREAD_ID]},
                json.loads(ledger_path.read_text(encoding="utf-8")),
            )

        with tempfile.TemporaryDirectory(prefix="pm-proxy-owner-invalid-") as temp:
            home = Path(temp)
            state_root = self.state_root(home)
            self.write_ticket(
                state_root, "malformed", external_thread_id=None, malformed=True
            )
            ledger_path = self.write_debt(
                state_root, [OWNER_DECISION_SINK_THREAD_ID]
            )
            invalid = invoke(
                "mcp__pm_proxy_orchestrator__pm_proxy_status",
                session_id="root-session",
                home=home,
            )
            self.assertIn("ROOT_LIFECYCLE_STATE_INVALID", invalid.stdout)
            self.assertEqual(
                {"root-session": [OWNER_DECISION_SINK_THREAD_ID]},
                json.loads(ledger_path.read_text(encoding="utf-8")),
            )

    def test_observation_debt_blocks_repeat_until_successful_watchdog(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pm-proxy-lifecycle-home-") as temp:
            home = Path(temp)
            state_root = home / ".codex" / "orchestrator-state"
            state_root.mkdir(parents=True, mode=0o700)
            os.chmod(state_root.parent, 0o700)
            observed = self.run_post(
                home,
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": "root-session",
                    "tool_name": "codex_appwait_threads",
                    "tool_input": {"targets": [{"threadId": "worker-1"}]},
                    "tool_response": {"status": "completed"},
                },
            )
            self.assertEqual(0, observed.returncode, observed.stderr)
            blocked = invoke(
                "codex_appwait_threads",
                tool_input={"targets": [{"threadId": "worker-1"}]},
                tool_use_id="wait-2",
                session_id="root-session",
                home=home,
            )
            payload = json.loads(blocked.stdout)
            self.assertEqual(
                "ROOT_LIFECYCLE_RECONCILIATION_REQUIRED",
                payload["hookSpecificOutput"]["permissionDecisionReason"],
            )
            watchdog_pre = invoke(
                "mcp__pm_proxy_orchestrator__pm_proxy_lifecycle_watchdog",
                tool_input={"external_thread_id": "worker-1"},
                session_id="root-session",
                home=home,
            )
            self.assertEqual("", watchdog_pre.stdout)
            cleared = self.run_post(
                home,
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": "root-session",
                    "tool_name": "mcp__pm_proxy_orchestrator__pm_proxy_lifecycle_watchdog",
                    "tool_input": {"external_thread_id": "worker-1"},
                    "tool_response": {
                        "structuredContent": {"ok": True, "result": {}}
                    },
                },
            )
            self.assertEqual(0, cleared.returncode, cleared.stderr)
            admitted = invoke(
                "codex_appwait_threads",
                tool_input={"targets": [{"threadId": "worker-1"}]},
                tool_use_id="wait-3",
                session_id="root-session",
                home=home,
            )
            self.assertEqual("", admitted.stdout)

    def test_pre_hook_records_observation_intent_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pm-proxy-lifecycle-pre-") as temp:
            home = Path(temp)
            state_root = home / ".codex" / "orchestrator-state"
            state_root.mkdir(parents=True, mode=0o700)
            os.chmod(state_root.parent, 0o700)
            admitted = invoke(
                "codex_appread_thread",
                tool_input={"threadId": "worker-before-dispatch"},
                session_id="root-session",
                home=home,
            )
            self.assertEqual("", admitted.stdout)
            blocked = invoke(
                "codex_appwait_threads",
                tool_input={"targets": [{"threadId": "worker-before-dispatch"}]},
                tool_use_id="wait-after-intent",
                session_id="root-session",
                home=home,
            )
            self.assertIn("ROOT_LIFECYCLE_RECONCILIATION_REQUIRED", blocked.stdout)

    def test_failed_watchdog_cannot_clear_debt_via_unrelated_nested_success(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="pm-proxy-lifecycle-result-") as temp:
            home = Path(temp)
            state_root = home / ".codex" / "orchestrator-state"
            state_root.mkdir(parents=True, mode=0o700)
            os.chmod(state_root.parent, 0o700)
            observed = self.run_post(
                home,
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": "root-session",
                    "tool_name": "codex_appread_thread",
                    "tool_input": {"threadId": "worker-1"},
                    "tool_response": {"status": "completed"},
                },
            )
            self.assertEqual(0, observed.returncode, observed.stderr)
            failed = self.run_post(
                home,
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": "root-session",
                    "tool_name": (
                        "mcp__pm_proxy_orchestrator__pm_proxy_lifecycle_watchdog"
                    ),
                    "tool_input": {"external_thread_id": "worker-1"},
                    "tool_response": {
                        "structuredContent": {
                            "ok": False,
                            "error": {"code": "synthetic-denial"},
                        },
                        "unrelated_transport_metadata": {
                            "structuredContent": {"ok": True}
                        },
                    },
                },
            )
            self.assertEqual(1, failed.returncode)
            ledger = json.loads(
                (state_root / ".dispatcher-lifecycle.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(["worker-1"], ledger["root-session"])
            cleared = self.run_post(
                home,
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": "root-session",
                    "tool_name": (
                        "mcp__pm_proxy_orchestrator__pm_proxy_lifecycle_watchdog"
                    ),
                    "tool_input": {"external_thread_id": "worker-1"},
                    "tool_response": {
                        "result": {"structuredContent": {"ok": True}}
                    },
                },
            )
            self.assertEqual(0, cleared.returncode, cleared.stderr)
            self.assertEqual(
                {},
                json.loads(
                    (state_root / ".dispatcher-lifecycle.json").read_text(
                        encoding="utf-8"
                    )
                ),
            )

    def test_control_schema_hold_clears_only_with_exact_revoked_grant_receipt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="pm-proxy-hold-hook-") as temp:
            home = Path(temp)
            state_root = home / ".codex" / "orchestrator-state"
            state_root.mkdir(parents=True, mode=0o700)
            os.chmod(state_root.parent, 0o700)
            observed = self.run_post(
                home,
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": "root-session",
                    "tool_name": "codex_appread_thread",
                    "tool_input": {"threadId": "worker-held"},
                    "tool_response": {"status": "completed"},
                },
            )
            self.assertEqual(0, observed.returncode, observed.stderr)
            response = {
                "structuredContent": {
                    "ok": True,
                    "operation": "acknowledge-control-schema-hold",
                    "result": {
                        "external_thread_id": "worker-held",
                        "hold_state": "CONTROL_SCHEMA_HOLD",
                        "required_action": "AWAIT_CONTROL_REPAIR",
                        "bootstrap_recovery_grant": {
                            "status": "REVOKED",
                            "consumed_before_dispatch": True,
                            "host_attested": True,
                        },
                    },
                }
            }
            mismatch = json.loads(json.dumps(response))
            mismatch["structuredContent"]["result"][
                "bootstrap_recovery_grant"
            ]["status"] = "ISSUED"
            rejected = self.run_post(
                home,
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": "root-session",
                    "tool_name": (
                        "mcp__pm_proxy_orchestrator__"
                        "pm_proxy_acknowledge_control_schema_hold"
                    ),
                    "tool_input": {"external_thread_id": "worker-held"},
                    "tool_response": mismatch,
                },
            )
            self.assertEqual(1, rejected.returncode)
            ledger = json.loads(
                (state_root / ".dispatcher-lifecycle.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(["worker-held"], ledger["root-session"])
            cleared = self.run_post(
                home,
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": "root-session",
                    "tool_name": (
                        "mcp__pm_proxy_orchestrator__"
                        "pm_proxy_acknowledge_control_schema_hold"
                    ),
                    "tool_input": {"external_thread_id": "worker-held"},
                    "tool_response": response,
                },
            )
            self.assertEqual(0, cleared.returncode, cleared.stderr)
            self.assertEqual(
                {},
                json.loads(
                    (state_root / ".dispatcher-lifecycle.json").read_text(
                        encoding="utf-8"
                    )
                ),
            )

    def test_busy_lifecycle_lock_denies_observation_quickly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pm-proxy-lifecycle-lock-") as temp:
            home = Path(temp)
            state_root = home / ".codex" / "orchestrator-state"
            state_root.mkdir(parents=True, mode=0o700)
            os.chmod(state_root.parent, 0o700)
            lock_path = state_root / ".dispatcher-lifecycle.lock"
            with lock_path.open("w", encoding="utf-8") as held:
                os.chmod(lock_path, 0o600)
                fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                started = time.monotonic()
                denied = invoke(
                    "codex_appread_thread",
                    tool_input={"threadId": "worker-under-contention"},
                    session_id="root-session",
                    home=home,
                )
                elapsed = time.monotonic() - started
            self.assertLess(elapsed, 2.0)
            self.assertIn("ROOT_LIFECYCLE_STATE_BUSY", denied.stdout)


if __name__ == "__main__":
    unittest.main()
