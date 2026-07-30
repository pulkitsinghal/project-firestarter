"""Lifecycle-watchdog regressions for evidence-derived terminalization."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from tests import test_orchestrator_control as existing_control_tests


ROOT = Path(__file__).resolve().parents[1]
CONTROL_ROOT = (
    ROOT / "addons" / "orchestrator_session" / "common" / "orchestrator-control"
)
CLI = CONTROL_ROOT / "orchestrator_control.py"
LEDGER = CONTROL_ROOT / "policy-ledger.json"
BASE_SHA = "a" * 40
NOW = "2026-07-29T18:00:00Z"

SPEC = importlib.util.spec_from_file_location("orchestrator_control_watchdog", CLI)
assert SPEC and SPEC.loader
control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(control)


class LifecycleWatchdogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = tempfile.TemporaryDirectory()
        self.root = Path(self.sandbox.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / ".git").mkdir()
        (self.repo / ".git" / "config").write_text(
            '[remote "origin"]\n'
            "    url = https://github.com/example/project.git\n",
            encoding="utf-8",
        )
        (self.repo / "docs").mkdir()
        (self.repo / "src").mkdir()
        self.state = self.root / "state"
        self.run_cli("init", now=NOW)

    def tearDown(self) -> None:
        self.sandbox.cleanup()

    def run_cli(
        self,
        command: str,
        request: dict[str, object] | None = None,
        *,
        now: str | None = None,
        expected: int = 0,
    ) -> dict[str, object]:
        arguments = [
            sys.executable,
            "-B",
            str(CLI),
            "--state-dir",
            str(self.state),
            "--policy-ledger",
            str(LEDGER),
            command,
        ]
        payload = None
        if request is not None:
            arguments.extend(["--request", "-"])
            payload = json.dumps(request)
        if now is not None:
            arguments.extend(["--now", now])
        completed = subprocess.run(
            arguments,
            cwd=ROOT,
            input=payload,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            expected,
            completed.returncode,
            f"stdout={completed.stdout}\nstderr={completed.stderr}",
        )
        stream = completed.stdout if completed.returncode == 0 else completed.stderr
        return json.loads(stream)

    def prepare_payload(
        self,
        suffix: str,
        *,
        path: str = "/docs",
        now: str = NOW,
    ) -> dict[str, object]:
        return {
            "interface_version": "1.0",
            "request_id": f"prepare-{suffix}",
            "source_event_key": f"source-{suffix}",
            "idempotency_key": f"idempotency-{suffix}",
            "outcome_key": f"outcome-{suffix}",
            "task_id": f"task-{suffix}",
            "title": f"Task {suffix}",
            "prompt": "Perform the bounded synthetic repository task.",
            "priority": 700,
            "target": {
                "remote": "https://github.com/example/project.git",
                "repo_root": str(self.repo),
                "path": path,
                "base_sha": BASE_SHA,
                "resource_mode": "path",
            },
            "context": {
                "owner": "owner",
                "org": "example",
                "repo": "github.com/example/project",
                "path": path,
                "environment": "local",
                "data_class": "public",
                "action": "task-launch",
                "task_kind": "implementation",
            },
            "dependencies": [],
            "permissions": ["isolated source and test work"],
            "prohibitions": ["no deployment"],
            "privacy_boundary": "Synthetic public source only.",
            "evidence_contract": ["exact candidate evidence"],
            "cleanup_duty": ["return resource disposition"],
            "lease_expires_at": "2026-07-30T18:00:00Z",
            "now": now,
        }

    def launch(
        self, suffix: str = "primary", *, path: str = "/docs"
    ) -> dict[str, object]:
        prepared = self.run_cli(
            "prepare-launch", self.prepare_payload(suffix, path=path)
        )
        required = prepared["result"]["envelope"]["receipt_required"]
        runtime_policy = required["runtime_policy"]
        receipt = {
            "interface_version": "1.0",
            "request_id": f"launch-receipt-{suffix}",
            "task_id": required["task_id"],
            "policy_snapshot_revision": required["policy_snapshot_revision"],
            "lease_epoch": required["lease_epoch"],
            "fencing_token": required["fencing_token"],
            "external_thread_id": f"thread-{suffix}",
            "applicable_rule_ids": required["applicable_rule_ids"],
            "runtime_attestation": {
                "root_model": runtime_policy["root_model"],
                "root_reasoning_effort": runtime_policy[
                    "root_reasoning_effort"
                ],
                "root_service_tier": runtime_policy["root_service_tier"],
                "root_fast_mode": runtime_policy["root_fast_mode"],
                "worker_model": runtime_policy["worker_model"],
                "worker_reasoning_effort": runtime_policy[
                    "worker_reasoning_effort"
                ],
                "worker_service_tier": runtime_policy["worker_service_tier"],
                "worker_fast_mode": runtime_policy["worker_fast_mode"],
                "service_tier_attestation": "config-verified",
                "tier_provenance": "trusted-project-and-user-config",
                "auth_mode": "chatgpt",
                "history_mode": "full-history",
                "parent_attestation_present": True,
            },
            "now": "2026-07-29T18:01:00Z",
        }
        self.run_cli("record-launch-receipt", receipt)
        return prepared

    @staticmethod
    def watch_request(
        prepared: dict[str, object],
        suffix: str,
        *,
        trigger: str,
        now: str,
        completion_signals: list[str] | None = None,
        remaining_work: dict[str, object] | None = None,
        worker_status: str = "running",
    ) -> dict[str, object]:
        required = prepared["result"]["envelope"]["receipt_required"]
        return {
            "interface_version": "1.0",
            "request_id": f"watch-{suffix}",
            "task_id": required["task_id"],
            "policy_snapshot_revision": required["policy_snapshot_revision"],
            "lease_epoch": required["lease_epoch"],
            "fencing_token": required["fencing_token"],
            "external_thread_id": "thread-primary",
            "action": "observe",
            "trigger": trigger,
            "worker_status": worker_status,
            "completion_signals": completion_signals or [],
            "evidence_refs": [f"evidence-{suffix}"],
            "remaining_work": remaining_work,
            "interrupt_receipt": None,
            "capacity": None,
            "now": now,
        }

    def completion_candidate(self) -> dict[str, object]:
        prepared = self.launch()
        request = self.watch_request(
            prepared,
            "objective-complete",
            trigger="worker-message",
            now="2026-07-29T18:02:00Z",
            completion_signals=["tests-passed", "output-ready"],
            remaining_work={
                "summary_code": "final-hashes-pending",
                "progress_ref": "hash-pass-1",
                "observed_at": "2026-07-29T18:02:00Z",
                "eta_seconds": 60,
            },
        )
        result = self.run_cli("lifecycle-watchdog", request)
        self.assertEqual(
            "COMPLETION_CANDIDATE",
            result["result"]["lifecycle"]["lifecycle_state"],
        )
        self.assertEqual(0, result["result"]["lifecycle"]["handback_deadline_checks"])
        return prepared

    def force_interrupt_required(
        self, prepared: dict[str, object]
    ) -> dict[str, object]:
        first = self.watch_request(
            prepared,
            "timeout-1",
            trigger="wait-timeout",
            now="2026-07-29T18:03:00Z",
            worker_status="running",
        )
        one = self.run_cli("lifecycle-watchdog", first)
        self.assertEqual(1, one["result"]["lifecycle"]["handback_deadline_checks"])
        second = self.watch_request(
            prepared,
            "timeout-2",
            trigger="before-status-claim",
            now="2026-07-29T18:04:00Z",
            worker_status="running",
        )
        two = self.run_cli("lifecycle-watchdog", second)
        self.assertEqual(
            "INTERRUPT_REQUIRED", two["result"]["lifecycle"]["lifecycle_state"]
        )
        self.assertEqual("TERMINALIZE", two["result"]["lifecycle"]["required_action"])
        return second

    def interrupt_request(
        self,
        prepared: dict[str, object],
        *,
        successor: dict[str, object] | None,
        suffix: str = "interrupt",
        empty_outcome: str = "EMPTY",
        blocked_audits: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        required = prepared["result"]["envelope"]["receipt_required"]
        return {
            "interface_version": "1.0",
            "request_id": f"watch-{suffix}",
            "task_id": required["task_id"],
            "policy_snapshot_revision": required["policy_snapshot_revision"],
            "lease_epoch": required["lease_epoch"],
            "fencing_token": required["fencing_token"],
            "external_thread_id": "thread-primary",
            "action": "interrupt-receipt",
            "trigger": "interrupt-receipt",
            "worker_status": "interrupted",
            "completion_signals": ["tests-passed"],
            "evidence_refs": ["terminalize-decision", "interrupt-receipt"],
            "remaining_work": None,
            "interrupt_receipt": {
                "receipt_id": f"interrupt-receipt-{suffix}",
                "external_thread_id": "thread-primary",
            },
            "capacity": {
                "configured_capacity": 1,
                "runnable_queue_count": 1 if successor is not None else 0,
                "empty_outcome": empty_outcome,
                "evidence_refs": ["receipt-backed-capacity"],
                "blocked_audits": blocked_audits or [],
                "successor_request": successor,
            },
            "now": "2026-07-29T18:05:00Z",
        }

    def test_completed_evidence_overrides_running_after_two_missed_checks(self) -> None:
        prepared = self.completion_candidate()
        self.force_interrupt_required(prepared)
        status = self.run_cli(
            "status", now="2026-07-29T18:04:30Z"
        )["result"]
        self.assertFalse(status["lifecycle_watchdog"]["status_claim_allowed"])
        self.assertEqual(
            ["task-primary"],
            status["lifecycle_watchdog"]["reconciliation_required_task_ids"],
        )
        self.assertTrue(status["tasks"][0]["capacity_eligible"])
        self.assertFalse(status["tasks"][0]["lifecycle"]["status_claim_allowed"])

    def test_concurrent_missed_checks_converge_on_interrupt_required(self) -> None:
        prepared = self.completion_candidate()
        requests = [
            self.watch_request(
                prepared,
                f"concurrent-timeout-{index}",
                trigger="wait-timeout",
                now=f"2026-07-29T18:03:0{index}Z",
            )
            for index in (1, 2)
        ]

        def reconcile(payload: dict[str, object]) -> dict[str, object]:
            return control.Plane(self.state, LEDGER).lifecycle_watchdog(payload)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reconcile, requests))
        states = {result["lifecycle"]["lifecycle_state"] for result in results}
        self.assertIn("INTERRUPT_REQUIRED", states)
        row = self.run_cli("status")["result"]["tasks"][0]["lifecycle"]
        self.assertEqual("INTERRUPT_REQUIRED", row["lifecycle_state"])
        self.assertEqual(2, row["handback_deadline_checks"])

    def test_fresh_reasoning_progress_remains_active(self) -> None:
        prepared = self.launch()
        first = self.watch_request(
            prepared,
            "reasoning-1",
            trigger="worker-message",
            now="2026-07-29T18:02:00Z",
            remaining_work={
                "summary_code": "reasoning",
                "progress_ref": "reasoning-pass-1",
                "observed_at": "2026-07-29T18:02:00Z",
                "eta_seconds": 300,
            },
        )
        one = self.run_cli("lifecycle-watchdog", first)
        self.assertEqual("RUNNING", one["result"]["lifecycle"]["lifecycle_state"])
        second = self.watch_request(
            prepared,
            "reasoning-2",
            trigger="worker-message",
            now="2026-07-29T18:03:00Z",
            remaining_work={
                "summary_code": "reasoning",
                "progress_ref": "reasoning-pass-2",
                "observed_at": "2026-07-29T18:03:00Z",
                "eta_seconds": 240,
            },
        )
        two = self.run_cli("lifecycle-watchdog", second)
        self.assertTrue(two["result"]["lifecycle"]["status_claim_allowed"])
        self.assertEqual(0, two["result"]["lifecycle"]["handback_deadline_checks"])

    def test_timestamp_only_progress_refresh_cannot_hold_capacity(self) -> None:
        prepared = self.completion_candidate()
        first = self.watch_request(
            prepared,
            "same-progress-1",
            trigger="worker-message",
            now="2026-07-29T18:02:30Z",
            remaining_work={
                "summary_code": "review",
                "progress_ref": "review-pass-1",
                "observed_at": "2026-07-29T18:02:30Z",
                "eta_seconds": 120,
            },
        )
        one = self.run_cli("lifecycle-watchdog", first)
        self.assertEqual(
            "COMPLETION_CANDIDATE",
            one["result"]["lifecycle"]["lifecycle_state"],
        )
        for index, now in enumerate(
            ("2026-07-29T18:03:00Z", "2026-07-29T18:03:30Z"),
            start=2,
        ):
            response = self.run_cli(
                "lifecycle-watchdog",
                self.watch_request(
                    prepared,
                    f"same-progress-{index}",
                    trigger="worker-message",
                    now=now,
                    remaining_work={
                        "summary_code": "review",
                        "progress_ref": "review-pass-1",
                        "observed_at": now,
                        "eta_seconds": 120,
                    },
                ),
            )
        self.assertEqual(
            "INTERRUPT_REQUIRED",
            response["result"]["lifecycle"]["lifecycle_state"],
        )
        self.assertEqual(
            "TERMINALIZE",
            response["result"]["lifecycle"]["required_action"],
        )

    def test_fresh_changed_progress_cancels_pending_interrupt(self) -> None:
        prepared = self.completion_candidate()
        self.force_interrupt_required(prepared)
        fresh = self.run_cli(
            "lifecycle-watchdog",
            self.watch_request(
                prepared,
                "recovered-progress",
                trigger="worker-message",
                now="2026-07-29T18:04:30Z",
                remaining_work={
                    "summary_code": "review",
                    "progress_ref": "review-pass-2",
                    "observed_at": "2026-07-29T18:04:30Z",
                    "eta_seconds": 120,
                },
            ),
        )
        self.assertEqual(
            "COMPLETION_CANDIDATE",
            fresh["result"]["lifecycle"]["lifecycle_state"],
        )
        self.assertEqual(0, fresh["result"]["lifecycle"]["handback_deadline_checks"])
        stale_interrupt = self.run_cli(
            "lifecycle-watchdog",
            self.interrupt_request(prepared, successor=None, suffix="stale"),
            expected=control.EXIT_CONFLICT,
        )
        self.assertEqual(
            "INTERRUPT_NOT_REQUIRED",
            stale_interrupt["error"]["code"],
        )

    def test_root_and_fifth_worker_reservations_fail_closed(self) -> None:
        root_request = self.prepare_payload("root-worker")
        root_request["task_id"] = "root"
        denied = self.run_cli(
            "prepare-launch",
            root_request,
            expected=control.EXIT_CONFLICT,
        )
        self.assertEqual("ROOT_WORKER_DENIED", denied["error"]["code"])

        for index in range(4):
            path = self.repo / f"lane-{index}"
            path.mkdir()
            self.launch(f"lane-{index}", path=f"/lane-{index}")
        overflow = self.prepare_payload("overflow", path="/")
        overflow["target"]["resource_mode"] = "repo-wide"
        full = self.run_cli(
            "prepare-launch",
            overflow,
            expected=control.EXIT_CONFLICT,
        )
        self.assertEqual("CAPACITY_FULL", full["error"]["code"])
        status = self.run_cli("status")["result"]
        self.assertEqual(4, status["worker_capacity"]["configured_capacity"])
        self.assertEqual(4, status["worker_capacity"]["active_or_reserved_count"])
        self.assertTrue(status["worker_capacity"]["root_excluded"])

    def test_schema_12_state_migrates_in_place_to_13(self) -> None:
        database = self.state / "orchestrator.sqlite3"
        with sqlite3.connect(database) as connection:
            connection.execute(
                "UPDATE metadata SET value='1.2' WHERE key='schema_version'"
            )
        migrated = self.run_cli(
            "init", now="2026-07-29T18:01:00Z"
        )["result"]
        self.assertEqual("1.3", migrated["schema_version"])
        with sqlite3.connect(database) as connection:
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertIn("lifecycle_watchdog", names)
        self.assertIn("lifecycle_watchdog_requests", names)

    def test_interrupt_receipt_atomically_refills_and_fences_archive(self) -> None:
        prepared = self.completion_candidate()
        self.force_interrupt_required(prepared)
        successor = self.prepare_payload(
            "successor", path="/src", now="2026-07-29T18:05:00Z"
        )
        interrupt = self.interrupt_request(prepared, successor=successor)
        result = self.run_cli("lifecycle-watchdog", interrupt)
        self.assertEqual("INTERRUPTED", result["result"]["lifecycle"]["lifecycle_state"])
        self.assertEqual("ARCHIVE_PENDING", self.task_state("task-primary"))
        self.assertEqual("LAUNCH_PENDING", self.task_state("task-successor"))
        self.assertEqual(
            "SUCCESSOR_RESERVED", result["result"]["capacity"]["outcome"]
        )
        replay = self.run_cli("lifecycle-watchdog", interrupt)
        self.assertEqual(result["result"]["capacity"], replay["result"]["capacity"])
        self.assertNotIn("prompt", replay["result"]["successor"])
        status = self.run_cli("status")["result"]
        self.assertEqual(
            ["task-successor"],
            [
                task["task_id"]
                for task in status["tasks"]
                if task["capacity_eligible"]
            ],
        )

    def test_clean_handback_marks_candidate_completed_and_not_active(self) -> None:
        prepared = self.completion_candidate()
        handback = existing_control_tests.ControlPlaneTests.handback(
            prepared,
            "primary",
            successor=None,
            now="2026-07-29T18:03:00Z",
        )
        result = self.run_cli("record-handback", handback)
        self.assertEqual("ARCHIVE_PENDING", result["result"]["state"])
        status = self.run_cli("status")["result"]
        primary = next(
            task for task in status["tasks"] if task["task_id"] == "task-primary"
        )
        self.assertEqual("COMPLETED", primary["lifecycle"]["lifecycle_state"])
        self.assertFalse(primary["capacity_eligible"])

    def test_interrupt_replay_tamper_and_stale_fence_fail_closed(self) -> None:
        prepared = self.completion_candidate()
        self.force_interrupt_required(prepared)
        interrupt = self.interrupt_request(
            prepared,
            successor=self.prepare_payload(
                "successor", path="/src", now="2026-07-29T18:05:00Z"
            ),
        )
        self.run_cli("lifecycle-watchdog", interrupt)
        altered_prompt = json.loads(json.dumps(interrupt))
        altered_prompt["capacity"]["successor_request"][
            "prompt"
        ] = "ALTERED REPLAY PROMPT"
        replay = self.run_cli("lifecycle-watchdog", altered_prompt)
        self.assertNotIn("prompt", replay["result"]["successor"])
        self.assertNotIn(
            "ALTERED REPLAY PROMPT",
            (self.state / "orchestrator.sqlite3").read_text(
                encoding="utf-8",
                errors="ignore",
            ),
        )
        changed_title = json.loads(json.dumps(interrupt))
        changed_title["capacity"]["successor_request"]["title"] = "Changed title"
        semantic_conflict = self.run_cli(
            "lifecycle-watchdog",
            changed_title,
            expected=control.EXIT_CONFLICT,
        )
        self.assertEqual(
            "IDEMPOTENCY_CONFLICT",
            semantic_conflict["error"]["code"],
        )
        changed = json.loads(json.dumps(interrupt))
        changed["interrupt_receipt"]["receipt_id"] = "changed-receipt"
        conflict = self.run_cli(
            "lifecycle-watchdog", changed, expected=control.EXIT_CONFLICT
        )
        self.assertEqual("IDEMPOTENCY_CONFLICT", conflict["error"]["code"])

    def test_interrupt_without_runnable_work_is_truthful_empty_and_not_active(
        self,
    ) -> None:
        prepared = self.completion_candidate()
        self.force_interrupt_required(prepared)
        result = self.run_cli(
            "lifecycle-watchdog",
            self.interrupt_request(prepared, successor=None),
        )
        self.assertEqual("EMPTY", result["result"]["capacity"]["outcome"])
        self.assertEqual(0, result["result"]["capacity"]["active_or_reserved_count"])
        status = self.run_cli("status")["result"]
        primary = next(
            task for task in status["tasks"] if task["task_id"] == "task-primary"
        )
        self.assertEqual("ARCHIVE_PENDING", primary["state"])
        self.assertFalse(primary["capacity_eligible"])

    def test_blocked_reaudit_can_fill_released_slot_without_new_successor(
        self,
    ) -> None:
        primary = self.completion_candidate()
        blocked = self.launch("blocked", path="/src")
        blocked_handback = existing_control_tests.ControlPlaneTests.handback(
            blocked,
            "blocked",
            disposition="blocked",
            block={
                "classification": "transient_tool",
                "reason_code": "TEMPORARY",
                "evidence_refs": ["blocked-evidence"],
            },
            now="2026-07-29T18:02:30Z",
        )
        self.run_cli("record-handback", blocked_handback)
        self.force_interrupt_required(primary)
        request = self.interrupt_request(
            primary,
            successor=None,
            suffix="resume-blocked",
            blocked_audits=[
                {
                    "task_id": "task-blocked",
                    "classification": "transient_tool",
                    "outcome": "resume",
                    "reason_code": "TOOL_RECOVERED",
                    "evidence_refs": ["recheck-pass"],
                }
            ],
        )
        request["capacity"]["configured_capacity"] = 1
        request["capacity"]["runnable_queue_count"] = 1
        result = self.run_cli("lifecycle-watchdog", request)
        self.assertEqual("CAPACITY_FULL", result["result"]["capacity"]["outcome"])
        self.assertEqual(1, result["result"]["capacity"]["active_or_reserved_count"])
        self.assertFalse(result["result"]["capacity"]["clean_handback"])
        self.assertEqual("RUNNING", self.task_state("task-blocked"))
        self.assertEqual("ARCHIVE_PENDING", self.task_state("task-primary"))

    def test_owner_gated_without_authority_audit_rolls_back(self) -> None:
        prepared = self.completion_candidate()
        self.force_interrupt_required(prepared)
        request = self.interrupt_request(
            prepared,
            successor=None,
            empty_outcome="OWNER_GATED",
        )
        denied = self.run_cli(
            "lifecycle-watchdog", request, expected=control.EXIT_CONFLICT
        )
        self.assertEqual("OWNER_GATE_EVIDENCE_REQUIRED", denied["error"]["code"])
        self.assertEqual("RUNNING", self.task_state("task-primary"))

    def test_interrupt_transaction_rolls_back_if_successor_reservation_crashes(
        self,
    ) -> None:
        prepared = self.completion_candidate()
        self.force_interrupt_required(prepared)
        request = self.interrupt_request(
            prepared,
            successor=self.prepare_payload(
                "successor", path="/src", now="2026-07-29T18:05:00Z"
            ),
        )
        plane = control.Plane(self.state, LEDGER)
        with mock.patch.object(
            plane, "reserve_launch", side_effect=RuntimeError("crash")
        ):
            with self.assertRaises(RuntimeError):
                plane.lifecycle_watchdog(request)
        with sqlite3.connect(self.state / "orchestrator.sqlite3") as connection:
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT count(*) FROM owner_claims WHERE task_id='task-primary' AND status='active'"
                ).fetchone()[0],
            )
            self.assertEqual(
                "RUNNING",
                connection.execute(
                    "SELECT state FROM tasks WHERE task_id='task-primary'"
                ).fetchone()[0],
            )
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT count(*) FROM tasks WHERE task_id='task-successor'"
                ).fetchone()[0],
            )

    def test_interrupt_before_terminalize_and_wrong_external_worker_refuse(
        self,
    ) -> None:
        prepared = self.completion_candidate()
        request = self.interrupt_request(prepared, successor=None)
        too_early = self.run_cli(
            "lifecycle-watchdog", request, expected=control.EXIT_CONFLICT
        )
        self.assertEqual("INTERRUPT_NOT_REQUIRED", too_early["error"]["code"])
        observe = self.watch_request(
            prepared,
            "wrong-worker",
            trigger="wait-timeout",
            now="2026-07-29T18:03:00Z",
        )
        observe["external_thread_id"] = "thread-mirror"
        wrong = self.run_cli(
            "lifecycle-watchdog", observe, expected=control.EXIT_CONFLICT
        )
        self.assertEqual("EXTERNAL_RECEIPT_MISMATCH", wrong["error"]["code"])
        stale = self.watch_request(
            prepared,
            "stale-fence",
            trigger="wait-timeout",
            now="2026-07-29T18:03:00Z",
        )
        stale["fencing_token"] = stale["fencing_token"] + 1
        refused = self.run_cli(
            "lifecycle-watchdog", stale, expected=control.EXIT_INVALID
        )
        self.assertEqual("STALE_FENCE", refused["error"]["code"])

    def task_state(self, task_id: str) -> str:
        status = self.run_cli("status")["result"]
        return next(
            task["state"] for task in status["tasks"] if task["task_id"] == task_id
        )


if __name__ == "__main__":
    unittest.main()
