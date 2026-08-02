from __future__ import annotations

import fcntl
import json
import os
import runpy
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "pre_tool_use_root_guard.py"


def invoke(
    tool_name: str,
    *,
    root: bool = True,
    tool_input: dict | None = None,
    tool_use_id: str | None = None,
    session_id: str = "synthetic-session",
    home: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if root:
        env["ROOT_ORCHESTRATOR_ROLE"] = "true"
    else:
        env.pop("ROOT_ORCHESTRATOR_ROLE", None)
    if home is not None:
        env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "session_id": session_id,
                "turn_id": "synthetic-turn",
                "tool_use_id": tool_use_id or f"call-{tool_name}",
                "tool_name": tool_name,
                "tool_input": tool_input or {"synthetic": True},
            }
        ),
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=5,
    )


class PreToolUseHookTest(unittest.TestCase):
    @staticmethod
    def write_launch_ticket(state: Path) -> tuple[dict, dict, str]:
        envelope = {
            "task_id": "avatar-rig",
            "source_event_key": "avatar-rig-source",
            "outcome_key": "avatar-rig-outcome",
            "policy_snapshot_revision": 1,
            "lease_epoch": 1,
            "fencing_token": 42,
        }
        ticket = {
            **envelope,
            "receipt": None,
            "receipt_deadline": "2099-01-01T00:00:00Z",
            "outbox": {"kind": "CREATE_THREAD", "outbox_id": "create:avatar-rig"},
        }
        ticket_path = state / "avatar-rig.ticket.json"
        ticket_path.write_text(json.dumps(ticket), encoding="utf-8")
        os.chmod(ticket_path, 0o600)
        prompt = (
            "SYNTHETIC\n\n<orchestrator_launch_envelope>\n"
            + json.dumps(envelope, sort_keys=True, separators=(",", ":"))
            + "\n</orchestrator_launch_envelope>"
        )
        return envelope, ticket, prompt

    def test_root_task_domain_families_are_denied_before_synthetic_dispatch(self):
        calls: list[str] = []
        tools = (
            "Bash",
            "apply_patch",
            "Agent",
            "mcp__filesystem__write_file",
            "mcp__codex_apps__browser_click",
            "mcp__codex_apps__sites_create_version",
        )
        for tool_name in tools:
            result = invoke(tool_name)
            self.assertEqual(0, result.returncode, result.stderr)
            decision = json.loads(result.stdout)
            self.assertEqual(
                "deny",
                decision["hookSpecificOutput"]["permissionDecision"],
            )
            if decision["hookSpecificOutput"]["permissionDecision"] != "deny":
                calls.append(tool_name)
        self.assertEqual([], calls)

    def test_unknown_and_invalid_events_fail_closed(self):
        unknown = invoke("new_specialized_local_tool")
        self.assertIn("UNKNOWN_TOOL_DENIED", unknown.stdout)
        invalid = subprocess.run(
            [sys.executable, str(HOOK)],
            input="not-json",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertIn("ROOT_GUARD_INVALID_EVENT", invalid.stdout)

    def test_control_plane_allowed_and_nonroot_has_no_decision(self):
        self.assertEqual("", invoke("codex_app__list_threads").stdout)
        self.assertEqual(
            "",
            invoke("mcp__pm_proxy_orchestrator__pm_proxy_doctor").stdout,
        )
        self.assertEqual("", invoke("Bash", root=False).stdout)

    def test_only_registered_pm_proxy_tools_are_allowed(self):
        server = runpy.run_path(str(ROOT / "scripts" / "mcp_server.py"))
        registered = server["TOOLS"]
        self.assertTrue(registered)
        for name in registered:
            admitted = invoke(f"mcp__pm_proxy_orchestrator__{name}")
            self.assertEqual("", admitted.stdout, name)
        unknown = invoke(
            "mcp__pm_proxy_orchestrator__pm_proxy_arbitrary_future_exec"
        )
        self.assertIn("ROOT_ORCHESTRATOR_UNKNOWN_TOOL_DENIED", unknown.stdout)

    def test_create_requires_fresh_exact_ticket_and_is_admitted_once(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-hook-home-") as temp:
            home = Path(temp)
            state = home / ".codex" / "orchestrator-state" / "session"
            state.mkdir(parents=True, mode=0o700)
            os.chmod(state.parent, 0o700)
            os.chmod(state.parent.parent, 0o700)
            _, ticket, prompt = self.write_launch_ticket(state)
            ticket_path = state / "avatar-rig.ticket.json"
            admitted = invoke(
                "codex_appcreate_thread",
                tool_input={"prompt": prompt},
                tool_use_id="create-call-1",
                home=home,
            )
            self.assertEqual("", admitted.stdout)
            ticket["receipt"] = {"external_thread_id": "thread-avatar-rig"}
            ticket_path.write_text(json.dumps(ticket), encoding="utf-8")
            os.chmod(ticket_path, 0o600)
            replay = invoke(
                "codex_appcreate_thread",
                tool_input={"prompt": prompt},
                tool_use_id="create-call-2",
                home=home,
            )
            self.assertIn("ROOT_CREATE_ALREADY_ADMITTED", replay.stdout)
            unreserved = invoke(
                "codex_appcreate_thread",
                tool_input={"prompt": "no envelope"},
                home=home,
            )
            self.assertIn("ROOT_CREATE_RESERVATION_REQUIRED", unreserved.stdout)

    def test_stale_admissions_are_pruned_before_capacity_check(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-hook-prune-") as temp:
            home = Path(temp)
            state = home / ".codex" / "orchestrator-state" / "session"
            state.mkdir(parents=True, mode=0o700)
            os.chmod(state.parent, 0o700)
            os.chmod(state.parent.parent, 0o700)
            _, _, prompt = self.write_launch_ticket(state)
            ledger_path = state / ".dispatcher-admissions.json"
            ledger_path.write_text(
                json.dumps({f"create:stale-{index}": f"call-{index}" for index in range(512)}),
                encoding="utf-8",
            )
            os.chmod(ledger_path, 0o600)
            admitted = invoke(
                "codex_appcreate_thread",
                tool_input={"prompt": prompt},
                tool_use_id="create-after-prune",
                home=home,
            )
            self.assertEqual("", admitted.stdout)
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual({"create:create:avatar-rig": "create-after-prune"}, ledger)

    def test_busy_admission_lock_denies_quickly_without_hook_timeout(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-hook-lock-") as temp:
            home = Path(temp)
            state = home / ".codex" / "orchestrator-state" / "session"
            state.mkdir(parents=True, mode=0o700)
            os.chmod(state.parent, 0o700)
            os.chmod(state.parent.parent, 0o700)
            _, _, prompt = self.write_launch_ticket(state)
            lock_path = state / ".dispatcher-admissions.lock"
            with lock_path.open("w", encoding="utf-8") as held:
                os.chmod(lock_path, 0o600)
                fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                started = time.monotonic()
                denied = invoke(
                    "codex_appcreate_thread",
                    tool_input={"prompt": prompt},
                    tool_use_id="create-under-contention",
                    home=home,
                )
                elapsed = time.monotonic() - started
            self.assertLess(elapsed, 2.0)
            self.assertIn("ROOT_ADMISSION_BUSY", denied.stdout)

    def test_nonprivate_admission_lock_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-hook-mode-") as temp:
            home = Path(temp)
            state = home / ".codex" / "orchestrator-state" / "session"
            state.mkdir(parents=True, mode=0o700)
            os.chmod(state.parent, 0o700)
            os.chmod(state.parent.parent, 0o700)
            _, _, prompt = self.write_launch_ticket(state)
            lock_path = state / ".dispatcher-admissions.lock"
            lock_path.write_text("", encoding="utf-8")
            os.chmod(lock_path, 0o644)
            denied = invoke(
                "codex_appcreate_thread",
                tool_input={"prompt": prompt},
                tool_use_id="create-nonprivate-lock",
                home=home,
            )
            self.assertIn("ROOT_ADMISSION_INVALID", denied.stdout)

    def test_archived_ticket_cannot_be_readmitted_after_archive_receipt(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-hook-archive-") as temp:
            home = Path(temp)
            state = home / ".codex" / "orchestrator-state" / "session"
            state.mkdir(parents=True, mode=0o700)
            os.chmod(state.parent, 0o700)
            os.chmod(state.parent.parent, 0o700)
            _, ticket, _ = self.write_launch_ticket(state)
            ticket["receipt"] = {"external_thread_id": "thread-avatar-rig"}
            ticket["handback"] = {"archive_receipt_at": "2026-08-02T04:00:00Z"}
            ticket_path = state / "avatar-rig.ticket.json"
            ticket_path.write_text(json.dumps(ticket), encoding="utf-8")
            os.chmod(ticket_path, 0o600)
            refill = {
                "sagas": {
                    "saga-1": {
                        "predecessor_task_id": "avatar-rig",
                        "outcome": "EMPTY",
                    }
                }
            }
            refill_path = state / "pm-proxy-refill-ledger.json"
            refill_path.write_text(json.dumps(refill), encoding="utf-8")
            os.chmod(refill_path, 0o600)
            denied = invoke(
                "codex_appset_thread_archived",
                tool_input={"threadId": "thread-avatar-rig", "archived": True},
                home=home,
            )
            self.assertIn("ROOT_ARCHIVE_REFILL_FENCE_REQUIRED", denied.stdout)

    def test_denial_prevents_synthetic_canary(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-hook-proof-") as temp:
            canary = Path(temp) / "should-not-exist"
            decision = json.loads(invoke("Bash").stdout)
            if decision["hookSpecificOutput"]["permissionDecision"] != "deny":
                canary.write_text("underlying executor ran", encoding="utf-8")
            self.assertFalse(canary.exists())


if __name__ == "__main__":
    unittest.main()
