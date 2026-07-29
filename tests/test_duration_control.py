"""Deterministic duration-lane, calibration, scheduling, and recovery contracts."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CONTROL_ROOT = (
    ROOT / "addons" / "orchestrator_session" / "common" / "orchestrator-control"
)
CLI = CONTROL_ROOT / "orchestrator_control.py"
LEDGER = CONTROL_ROOT / "policy-ledger.json"
NOW = "2026-07-29T03:30:00Z"
BASE_SHA = "a" * 40
CALIBRATION_SHA256 = (
    "c3739bb1abff972ba6a85ecacfd9b794c6843d972b2ff90320b7eef67030585a"
)

SPEC = importlib.util.spec_from_file_location("duration_control", CLI)
assert SPEC and SPEC.loader
control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(control)


class DurationControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.sandbox.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / ".git").mkdir()
        (self.repo / ".git" / "config").write_text(
            '[remote "origin"]\n'
            "    url = https://github.com/example/project.git\n",
            encoding="utf-8",
        )
        for name in ("docs", "src"):
            (self.repo / name).mkdir()
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
        if request is not None:
            arguments.extend(["--request", "-"])
        if now is not None:
            arguments.extend(["--now", now])
        completed = subprocess.run(
            arguments,
            cwd=ROOT,
            input=None if request is None else json.dumps(request),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            expected,
            completed.returncode,
            f"stdout={completed.stdout}\nstderr={completed.stderr}",
        )
        return json.loads(
            completed.stdout if completed.returncode == 0 else completed.stderr
        )

    @staticmethod
    def estimate(
        bucket: str = "5m",
        *,
        family: str = "read-only-audit",
        setup: int | None = 30,
        test: int | None = 180,
    ) -> dict[str, object]:
        return {
            "estimate_version": 7,
            "estimated_bucket": bucket,
            "confidence": "moderate",
            "task_family": family,
            "tool_family": "local-cli",
            "environment_class": "macos-local",
            "evidence_basis": [
                "calibration-c3739bb1",
                "completed-observation",
            ],
            "expected_components": {
                "setup_seconds": setup,
                "test_seconds": test,
                "remote_wait_seconds": None,
            },
            "heavyweight_concurrency_cap": 1,
        }

    def prepare_request(
        self,
        suffix: str,
        *,
        path: str = "/docs",
        estimate: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "interface_version": "1.0",
            "request_id": f"prepare-{suffix}",
            "source_event_key": f"source-{suffix}",
            "idempotency_key": f"idempotency-{suffix}",
            "outcome_key": f"outcome-{suffix}",
            "task_id": f"task-{suffix}",
            "title": f"Task {suffix}",
            "prompt": "Synthetic bounded task.",
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
            "permissions": ["isolated edits"],
            "prohibitions": ["no deployment"],
            "privacy_boundary": "Synthetic public evidence only.",
            "evidence_contract": ["typed evidence"],
            "cleanup_duty": ["release claim"],
            "duration_estimate": estimate or self.estimate(),
            "lease_expires_at": "2026-07-30T03:30:00Z",
            "now": NOW,
        }

    def launch(
        self, suffix: str, *, estimate: dict[str, object] | None = None
    ) -> tuple[dict[str, object], dict[str, object]]:
        prepared = self.run_cli(
            "prepare-launch", self.prepare_request(suffix, estimate=estimate)
        )
        required = prepared["result"]["envelope"]["receipt_required"]
        receipt = {
            "interface_version": "1.0",
            "request_id": f"receipt-{suffix}",
            "task_id": required["task_id"],
            "policy_snapshot_revision": required["policy_snapshot_revision"],
            "lease_epoch": required["lease_epoch"],
            "fencing_token": required["fencing_token"],
            "external_thread_id": f"thread-{suffix}",
            "applicable_rule_ids": required["applicable_rule_ids"],
            "now": "2026-07-29T03:31:00Z",
        }
        self.run_cli("record-launch-receipt", receipt)
        return prepared, receipt

    @staticmethod
    def actual(
        active: int,
        *,
        queue: int | None = 3,
        setup: int | None = 10,
        tool_wait: int | None = 5,
        external_wait: int | None = None,
        wall: int | None = None,
        first: int | None = 12,
        close: int | None = None,
    ) -> dict[str, int | None]:
        return {
            "active_seconds": active,
            "queue_seconds": queue,
            "setup_seconds": setup,
            "tool_wait_seconds": tool_wait,
            "external_wait_seconds": external_wait,
            "total_wall_seconds": wall if wall is not None else active + 100,
            "first_evidence_seconds": first,
            "safe_close_seconds": close,
        }

    def progress(
        self,
        receipt: dict[str, object],
        suffix: str,
        *,
        active: int,
        runtime_state: str = "active",
        successor: dict[str, object] | None = None,
        wall: int | None = None,
    ) -> dict[str, object]:
        return {
            "interface_version": "1.0",
            "request_id": f"progress-{suffix}",
            "task_id": receipt["task_id"],
            "policy_snapshot_revision": receipt["policy_snapshot_revision"],
            "lease_epoch": receipt["lease_epoch"],
            "fencing_token": receipt["fencing_token"],
            "external_thread_id": receipt["external_thread_id"],
            "runtime_state": runtime_state,
            "actual": self.actual(active, wall=wall),
            "successor_request": successor,
            "now": "2026-07-29T03:40:00Z",
        }

    def observation(
        self,
        receipt: dict[str, object],
        suffix: str,
        active: int,
    ) -> dict[str, object]:
        return {
            "interface_version": "1.0",
            "request_id": f"observation-{suffix}",
            "sample_id": f"sample-{suffix}",
            "task_id": receipt["task_id"],
            "policy_snapshot_revision": receipt["policy_snapshot_revision"],
            "lease_epoch": receipt["lease_epoch"],
            "fencing_token": receipt["fencing_token"],
            "external_thread_id": receipt["external_thread_id"],
            "completed": True,
            "actual": self.actual(
                active,
                queue=7,
                setup=11,
                tool_wait=13,
                external_wait=None,
                wall=active + 60,
                first=min(active, 17),
                close=None,
            ),
            "evidence_refs": ["typed-check-1"],
            "now": "2026-07-29T04:00:00Z",
        }

    def test_exact_bucket_assignment_and_prepare_receipt_contract(self) -> None:
        boundaries = {
            0: "seconds",
            59: "seconds",
            60: "5m",
            449: "5m",
            450: "10m",
            749: "10m",
            750: "15m",
            1049: "15m",
            1050: "20m",
            1499: "20m",
            1500: "30m",
            2249: "30m",
            2250: "45m",
            3149: "45m",
            3150: "60m+",
        }
        for seconds, expected in boundaries.items():
            self.assertEqual(expected, control.bucket_for_seconds(seconds))
        prepared, receipt = self.launch("bucket")
        envelope = prepared["result"]["envelope"]
        self.assertEqual(self.estimate(), envelope["duration_estimate"])
        self.assertEqual(
            envelope["duration_estimate"],
            envelope["receipt_required"]["duration_estimate"],
        )
        launched = self.run_cli(
            "record-launch-receipt",
            {**receipt, "request_id": "receipt-bucket-replay"},
        )
        self.assertEqual(
            "5m", launched["result"]["duration_estimate"]["current_lane"]
        )
        self.assertEqual(CALIBRATION_SHA256[:8], "c3739bb1")

    def test_waiting_exclusion_rollover_extremes_and_early_finish(self) -> None:
        _prepared, receipt = self.launch("roll")
        waiting = self.run_cli(
            "record-duration-progress",
            self.progress(
                receipt,
                "waiting",
                active=100,
                runtime_state="waiting",
                wall=1_000,
            ),
        )
        self.assertFalse(waiting["result"]["reclassified"])
        self.assertEqual(
            ["NON_RUNTIME_WAIT_EXCLUDED"], waiting["result"]["reason_codes"]
        )
        rolled_request = self.progress(receipt, "roll", active=451, wall=1_100)
        rolled = self.run_cli("record-duration-progress", rolled_request)
        self.assertTrue(rolled["result"]["reclassified"])
        self.assertEqual(("5m", "10m"), (
            rolled["result"]["from_bucket"],
            rolled["result"]["to_bucket"],
        ))
        self.assertFalse(rolled["result"]["worker_restart_required"])
        self.assertEqual(receipt["fencing_token"], rolled["result"]["fencing_token"])
        replay = self.run_cli("record-duration-progress", rolled_request)
        self.assertEqual(rolled["result"], replay["result"])
        terminal_observation = self.observation(receipt, "roll", 50)
        terminal_observation["actual"]["safe_close_seconds"] = 100
        observed = self.run_cli(
            "record-duration-observation", terminal_observation
        )
        self.assertTrue(observed["result"]["early_finish"])
        self.assertEqual("seconds", observed["result"]["actual_bucket"])
        self.assertIsNone(
            observed["result"]["duration"]["actual"]["external_wait_seconds"]
        )
        self.assertEqual(
            17,
            observed["result"]["duration"]["actual"]["first_evidence_seconds"],
        )
        self.assertEqual(
            100,
            observed["result"]["duration"]["actual"]["safe_close_seconds"],
        )

        self.run_cli(
            "record-duration-observation",
            {
                **self.observation(receipt, "censored", 10),
                "completed": False,
            },
            expected=2,
        )

    def test_atomic_reclassification_refills_released_lane_once(self) -> None:
        _prepared, receipt = self.launch(
            "extreme", estimate=self.estimate("seconds", setup=5, test=20)
        )
        successor = self.prepare_request(
            "short-successor",
            path="/src",
            estimate=self.estimate("seconds", family="duplicate-stop", setup=1, test=5),
        )
        request = self.progress(
            receipt,
            "extreme",
            active=3_150,
            successor=successor,
            wall=3_300,
        )
        result = self.run_cli("record-duration-progress", request)["result"]
        self.assertEqual("60m+", result["to_bucket"])
        self.assertIn("TWO_BUCKETS_SKIPPED", result["reason_codes"])
        self.assertEqual(
            "task-short-successor", result["successor"]["envelope"]["task_id"]
        )
        status = self.run_cli(
            "status", now="2026-07-30T03:31:00Z"
        )["result"]
        self.assertEqual(1, status["duration"]["receipt_backed_lane_counts"]["60m+"])
        self.assertEqual(0, status["duration"]["receipt_backed_lane_counts"]["seconds"])
        self.assertEqual(
            1, status["duration"]["reserved_setup_lane_counts"]["seconds"]
        )
        self.assertTrue(status["duration"]["root_excluded_from_worker_capacity"])
        self.assertEqual("EVALUATED", status["duration"]["freshness"]["state"])
        current = next(
            task for task in status["tasks"] if task["task_id"] == "task-extreme"
        )
        self.assertTrue(current["freshness"]["stale"])

    def test_duplicate_reclassification_race_has_one_successor(self) -> None:
        _prepared, receipt = self.launch(
            "race", estimate=self.estimate("seconds", setup=1, test=10)
        )
        barrier = threading.Barrier(2)
        outcomes: list[tuple[str, object]] = []

        def contender(index: int) -> None:
            successor = self.prepare_request(
                "race-successor",
                path="/src",
                estimate=self.estimate("seconds"),
            )
            request = self.progress(
                receipt,
                f"race-{index}",
                active=500,
                successor=successor,
            )
            barrier.wait()
            try:
                value = control.Plane(self.state, LEDGER).record_duration_progress(
                    request
                )
                outcomes.append(("ok", value))
            except control.ControlError as error:
                outcomes.append(("error", error.code))

        threads = [threading.Thread(target=contender, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(1, sum(kind == "ok" for kind, _ in outcomes))
        connection = sqlite3.connect(self.state / "orchestrator.sqlite3")
        try:
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT count(*) FROM tasks WHERE task_id='task-race-successor'"
                ).fetchone()[0],
            )
        finally:
            connection.close()

    def test_reclassification_crash_rolls_back_then_recovers(self) -> None:
        _prepared, receipt = self.launch(
            "crash", estimate=self.estimate("seconds", setup=1, test=10)
        )
        request = self.progress(receipt, "crash", active=500)
        plane = control.Plane(self.state, LEDGER)
        with mock.patch.object(
            control.Plane, "event", side_effect=RuntimeError("synthetic crash")
        ):
            with self.assertRaises(RuntimeError):
                plane.record_duration_progress(request)
        connection = sqlite3.connect(self.state / "orchestrator.sqlite3")
        try:
            self.assertEqual(
                "seconds",
                connection.execute(
                    "SELECT current_lane FROM task_timing WHERE task_id='task-crash'"
                ).fetchone()[0],
            )
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT count(*) FROM duration_progress WHERE request_id='progress-crash'"
                ).fetchone()[0],
            )
        finally:
            connection.close()
        recovered = plane.record_duration_progress(request)
        self.assertTrue(recovered["reclassified"])
        self.assertEqual("10m", recovered["to_bucket"])

    def test_sparse_and_conflicting_calibration_fail_closed(self) -> None:
        sparse = self.run_cli(
            "duration-estimate",
            {
                "interface_version": "1.0",
                "request_id": "estimate-sparse",
                "task_family": "read-only-audit",
                "tool_family": "local-cli",
                "environment_class": "macos-local",
                "minimum_estimate_version": 8,
                "now": NOW,
            },
        )["result"]
        self.assertEqual("SPARSE_EVIDENCE", sparse["state"])
        self.assertFalse(sparse["automatic"])
        self.assertIsNone(sparse["estimate"])

        connection = sqlite3.connect(self.state / "orchestrator.sqlite3")
        try:
            samples = [
                ("conflict", "conflicting-family", active)
                for active in (20, 30, 500, 600, 3_200)
            ] + [
                ("learned", "stable-family", active)
                for active in (500, 510, 520, 530, 540)
            ]
            for index, (prefix, family, active) in enumerate(samples):
                connection.execute(
                    """INSERT INTO tasks(
                      task_id,source_event_key,idempotency_key,outcome_key,state,
                      priority,dependencies_json,target_json,prompt_reference,
                      policy_revision,applicable_rule_ids_json,lease_epoch,
                      fencing_token,created_at,updated_at,source
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        f"{prefix}-task-{index}",
                        f"{prefix}-source-{index}",
                        f"{prefix}-idem-{index}",
                        f"{prefix}-outcome-{index}",
                        "ARCHIVED",
                        1,
                        "[]",
                        "{}",
                        f"{prefix}-source-{index}",
                        1,
                        "[]",
                        1,
                        100 + index,
                        NOW,
                        NOW,
                        "synthetic-test",
                    ),
                )
                connection.execute(
                    """INSERT INTO duration_samples VALUES(
                      ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                    )""",
                    (
                        f"{prefix}-{index}",
                        f"hash-{index}",
                        f"{prefix}-task-{index}",
                        family,
                        "local-cli",
                        "macos-local",
                        "5m",
                        control.bucket_for_seconds(active),
                        1,
                        active,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        "[]",
                        NOW,
                    ),
                )
            connection.commit()
        finally:
            connection.close()
        conflict = self.run_cli(
            "duration-estimate",
            {
                "interface_version": "1.0",
                "request_id": "estimate-conflict",
                "task_family": "conflicting-family",
                "tool_family": "local-cli",
                "environment_class": "macos-local",
                "minimum_estimate_version": 2,
                "now": NOW,
            },
        )["result"]
        self.assertEqual("CONFLICTING_EVIDENCE", conflict["state"])
        self.assertFalse(conflict["automatic"])
        learned = self.run_cli(
            "duration-estimate",
            {
                "interface_version": "1.0",
                "request_id": "estimate-learned",
                "task_family": "stable-family",
                "tool_family": "local-cli",
                "environment_class": "macos-local",
                "minimum_estimate_version": 9,
                "now": NOW,
            },
        )["result"]
        self.assertEqual("LEARNED_PRIOR_AVAILABLE", learned["state"])
        self.assertTrue(learned["automatic"])
        self.assertEqual("10m", learned["estimate"]["estimated_bucket"])
        self.assertEqual(9, learned["estimate"]["estimate_version"])

    def test_schedule_fairness_heavy_cap_setup_recovery_and_idle_truth(self) -> None:
        request = {
            "interface_version": "1.0",
            "request_id": "schedule-1",
            "active_heavyweight": 1,
            "heavyweight_concurrency_cap": 1,
            "short_lane_available": True,
            "capacity_deficit": True,
            "candidates": [
                {
                    "candidate_id": "queued-setup",
                    "bucket": "10m",
                    "runtime_state": "active",
                    "setup_state": "queued_setup",
                    "priority": 999,
                    "queue_seconds": 10,
                },
                {
                    "candidate_id": "failed-setup",
                    "bucket": "seconds",
                    "runtime_state": "active",
                    "setup_state": "failed",
                    "priority": 998,
                    "queue_seconds": 20,
                },
                {
                    "candidate_id": "next-short",
                    "bucket": "5m",
                    "runtime_state": "active",
                    "setup_state": "ready",
                    "priority": 500,
                    "queue_seconds": 30,
                },
                {
                    "candidate_id": "old-heavy",
                    "bucket": "60m+",
                    "runtime_state": "active",
                    "setup_state": "ready",
                    "priority": 900,
                    "queue_seconds": 10_000,
                },
                {
                    "candidate_id": "waiting",
                    "bucket": "seconds",
                    "runtime_state": "waiting",
                    "setup_state": "ready",
                    "priority": 1_000,
                    "queue_seconds": 20_000,
                },
            ],
            "now": NOW,
        }
        scheduled = self.run_cli("duration-schedule", request)["result"]
        self.assertEqual("next-short", scheduled["selected_candidate_id"])
        self.assertEqual("SHORT_LANE_ANTI_STARVATION", scheduled["selected_reason"])
        self.assertFalse(scheduled["owner_prompt_required"])
        self.assertEqual(
            "CALLER_MUST_EXECUTE_RECEIPT_BACKED_PREPARE",
            scheduled["dispatch_contract"],
        )
        self.assertEqual(
            {
                "queued_setup_reserved_count": 1,
                "queued_setup_active_count": 0,
                "failed_setup_rollback_count": 1,
                "resource_held_queued_count": 1,
                "resource_held_queued_weight": 1,
                "active_resource_weight": 0,
                "heavy_resource_active_or_reserved_count": 0,
                "root_excluded_from_logical_capacity": True,
                "process_oversubscription_inferred": False,
            },
            scheduled["reservation_summary"],
        )
        reasons = {item["candidate_id"]: item["reason_code"] for item in scheduled["deferred"]}
        self.assertEqual("HEAVYWEIGHT_CAP", reasons["old-heavy"])
        self.assertEqual(
            "SETUP_FAILED_RESERVATION_ROLLED_BACK", reasons["failed-setup"]
        )

        empty = self.run_cli(
            "duration-schedule",
            {
                **request,
                "request_id": "schedule-empty",
                "candidates": [],
            },
        )["result"]
        self.assertEqual("EMPTY", empty["outcome"])
        self.assertFalse(empty["dispatch_required"])
        self.assertFalse(empty["owner_prompt_required"])
        self.assertEqual("NO_DISPATCH_EMPTY", empty["dispatch_contract"])
        full = self.run_cli(
            "duration-schedule",
            {
                **request,
                "request_id": "schedule-full",
                "capacity_deficit": False,
                "candidates": [
                    {
                        "candidate_id": "would-overfill",
                        "bucket": "seconds",
                        "runtime_state": "active",
                        "setup_state": "ready",
                        "priority": 1_000,
                        "queue_seconds": 1_000,
                    }
                ],
            },
        )["result"]
        self.assertEqual("CAPACITY_FULL", full["outcome"])
        self.assertFalse(full["dispatch_required"])
        self.assertEqual(
            "NO_DISPATCH_CAPACITY_FULL", full["dispatch_contract"]
        )

    def test_resource_aware_schedule_serializes_heavy_group_but_keeps_light_parallel(
        self,
    ) -> None:
        def profile(
            resource_class: str,
            group: str | None,
            *,
            weight: int = 1,
            cap: int = 4,
        ) -> dict[str, object]:
            return {
                "resource_class": resource_class,
                "exclusive_group": group,
                "weight": weight,
                "cap": cap,
            }

        base = {
            "interface_version": "1.0",
            "request_id": "resource-aware",
            "active_heavyweight": 0,
            "heavyweight_concurrency_cap": 4,
            "short_lane_available": False,
            "capacity_deficit": True,
            "resource_holds": [
                {
                    "holder_id": "active-native-build",
                    "state": "active",
                    "resource_profile": profile(
                        "heavy", "native-build", weight=2, cap=4
                    ),
                },
                {
                    "holder_id": "queued-database-migration",
                    "state": "queued_setup",
                    "resource_profile": profile(
                        "heavy", "database-migration", weight=1, cap=2
                    ),
                },
            ],
            "candidates": [
                {
                    "candidate_id": "same-group-heavy",
                    "bucket": "20m",
                    "runtime_state": "active",
                    "setup_state": "ready",
                    "priority": 1000,
                    "queue_seconds": 500,
                    "resource_profile": profile(
                        "heavy", "native-build", weight=1, cap=4
                    ),
                },
                {
                    "candidate_id": "portfolio-recovery-light",
                    "bucket": "5m",
                    "runtime_state": "active",
                    "setup_state": "ready",
                    "priority": 900,
                    "queue_seconds": 400,
                    "resource_profile": profile(
                        "light", "native-build", weight=1, cap=4
                    ),
                },
                {
                    "candidate_id": "weight-capped-light",
                    "bucket": "5m",
                    "runtime_state": "active",
                    "setup_state": "ready",
                    "priority": 800,
                    "queue_seconds": 300,
                    "resource_profile": profile(
                        "light", "database-migration", weight=2, cap=2
                    ),
                },
            ],
            "now": NOW,
        }
        scheduled = self.run_cli("duration-schedule", base)["result"]
        self.assertEqual(
            "portfolio-recovery-light", scheduled["selected_candidate_id"]
        )
        reasons = {
            item["candidate_id"]: item["reason_code"]
            for item in scheduled["deferred"]
        }
        self.assertEqual(
            "HEAVY_EXCLUSIVE_GROUP_HELD", reasons["same-group-heavy"]
        )
        self.assertEqual(
            "RESOURCE_WEIGHT_CAP", reasons["weight-capped-light"]
        )
        self.assertEqual(
            {
                "resource_class": "light",
                "exclusive_group": "native-build",
                "weight": 1,
                "cap": 4,
            },
            scheduled["selected_resource_profile"],
        )
        summary = scheduled["reservation_summary"]
        self.assertEqual(1, summary["resource_held_queued_count"])
        self.assertEqual(1, summary["resource_held_queued_weight"])
        self.assertEqual(2, summary["active_resource_weight"])
        self.assertEqual(
            2, summary["heavy_resource_active_or_reserved_count"]
        )
        self.assertTrue(summary["root_excluded_from_logical_capacity"])
        self.assertFalse(summary["process_oversubscription_inferred"])

        queued_holds_group = {
            **base,
            "request_id": "resource-queued-hold",
            "resource_holds": [],
            "candidates": [
                {
                    "candidate_id": "queued-heavy",
                    "bucket": "20m",
                    "runtime_state": "active",
                    "setup_state": "queued_setup",
                    "priority": 1000,
                    "queue_seconds": 20,
                    "resource_profile": profile("heavy", "native-build"),
                },
                {
                    "candidate_id": "ready-heavy",
                    "bucket": "20m",
                    "runtime_state": "active",
                    "setup_state": "ready",
                    "priority": 900,
                    "queue_seconds": 10,
                    "resource_profile": profile("heavy", "native-build"),
                },
            ],
        }
        queued = self.run_cli(
            "duration-schedule", queued_holds_group
        )["result"]
        self.assertIsNone(queued["selected_candidate_id"])
        self.assertEqual(
            "HEAVY_EXCLUSIVE_GROUP_HELD",
            {
                item["candidate_id"]: item["reason_code"]
                for item in queued["deferred"]
            }["ready-heavy"],
        )
        self.assertEqual(
            1, queued["reservation_summary"]["resource_held_queued_count"]
        )

    def test_resource_schedule_rejects_private_group_and_invalid_weight_cap(
        self,
    ) -> None:
        candidate = {
            "candidate_id": "unsafe-resource",
            "bucket": "5m",
            "runtime_state": "active",
            "setup_state": "ready",
            "priority": 1,
            "queue_seconds": 0,
            "resource_profile": {
                "resource_class": "light",
                "exclusive_group": "private/repository",
                "weight": 1,
                "cap": 1,
            },
        }
        base = {
            "interface_version": "1.0",
            "request_id": "unsafe-resource",
            "active_heavyweight": 0,
            "heavyweight_concurrency_cap": 1,
            "short_lane_available": True,
            "capacity_deficit": True,
            "resource_holds": [],
            "candidates": [candidate],
            "now": NOW,
        }
        denied = self.run_cli("duration-schedule", base, expected=2)
        self.assertEqual("PRIVACY_REJECTED", denied["error"]["code"])
        candidate["resource_profile"] = {
            "resource_class": "heavy",
            "exclusive_group": "native-build",
            "weight": 2,
            "cap": 1,
        }
        base["request_id"] = "invalid-resource-weight"
        denied = self.run_cli("duration-schedule", base, expected=2)
        self.assertEqual("SCHEMA_INVALID", denied["error"]["code"])

    def test_prepare_enforces_heavyweight_cap_for_active_or_reserved(self) -> None:
        heavy = self.estimate("60m+", family="control-plane-build")
        self.run_cli(
            "prepare-launch",
            self.prepare_request("heavy-one", estimate=heavy),
        )
        rejected = self.run_cli(
            "prepare-launch",
            self.prepare_request("heavy-two", path="/src", estimate=heavy),
            expected=3,
        )
        self.assertEqual("HEAVYWEIGHT_CAP", rejected["error"]["code"])
        status = self.run_cli("status")["result"]
        self.assertEqual(
            1, status["duration"]["reserved_setup_lane_counts"]["60m+"]
        )
        self.assertEqual(
            0, status["duration"]["receipt_backed_lane_counts"]["60m+"]
        )

    def test_duration_privacy_rejects_paths_and_durable_state_has_no_prompt(self) -> None:
        marker = "verbatim-private-prompt-marker"
        invalid = self.prepare_request(
            "private-label",
            estimate={
                **self.estimate(),
                "task_family": "/Users/private/repository",
            },
        )
        invalid["prompt"] = marker
        self.run_cli("prepare-launch", invalid, expected=2)
        valid = self.prepare_request("privacy")
        valid["prompt"] = marker
        self.run_cli("prepare-launch", valid)
        data = (self.state / "orchestrator.sqlite3").read_bytes()
        self.assertNotIn(marker.encode(), data)
        self.assertNotIn(
            str(self.repo).encode(),
            json.dumps(
                self.run_cli(
                    "duration-estimate",
                    {
                        "interface_version": "1.0",
                        "request_id": "privacy-estimate",
                        "task_family": "read-only-audit",
                        "tool_family": "local-cli",
                        "environment_class": "macos-local",
                        "minimum_estimate_version": 1,
                        "now": NOW,
                    },
                )
            ).encode(),
        )


if __name__ == "__main__":
    unittest.main()
