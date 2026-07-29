"""Receipt-feed 1.0 adapter and dashboard consumer contract tests."""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (
    ROOT / "addons" / "orchestrator_session" / "common" / "orchestrator-control"
)
EXPORTER_PATH = CONTROL / "receipt_feed_exporter.py"
SCHEMA_PATH = CONTROL / "schemas" / "receipt-feed-1.0.schema.json"
DASHBOARD_PATH = CONTROL / "dashboard.html"
CONTROL_CLI = CONTROL / "orchestrator_control.py"
POLICY_LEDGER = CONTROL / "policy-ledger.json"
SYNTHETIC_STATE = CONTROL / "receipt-feed" / "synthetic-current-state.json"
SPEC = importlib.util.spec_from_file_location("receipt_feed_exporter", EXPORTER_PATH)
assert SPEC and SPEC.loader
EXPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORTER)


GENERATED = "2026-07-28T15:00:00Z"
SERVED = "2026-07-28T15:00:05Z"
PRIVATE_TASK = "123e4567-e89b-12d3-a456-426614174000"
PRIVATE_PATH = "/Users/private/project"


def identity(index: int) -> dict[str, str]:
    return {
        "sourceEventKey": f"event-{index}",
        "outcomeKey": f"outcome-{index}",
        "receiptKind": "task",
        "canonicalOwnerKey": f"owner-{index}",
    }


def task(
    key: str,
    state: str,
    *,
    block: dict[str, object] | None = None,
    duration: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "task_id": key,
        "state": state,
        "priority": 100,
        "repo_alias": "private-repo",
        "path": PRIVATE_PATH,
        "canonical_external_thread_id": (
            f"external-{key}" if state == "RUNNING" else None
        ),
        "capacity_eligible": state in {"LAUNCH_PENDING", "RUNNING"},
        "updated_at": GENERATED,
        "block": block,
        "duration": duration,
        "freshness": {
            "evaluated_at": GENERATED,
            "lease_expires_at": "2026-07-28T15:10:00Z",
            "stale": False,
            "state": "FRESH",
        },
    }


def fact(
    key: str,
    index: int,
    *,
    revision: int = 1,
    gate: str | None = None,
    depends: list[str] | None = None,
    successors: list[str] | None = None,
    terminal_leaf: bool = False,
    mirror_of: str | None = None,
    evidence: list[dict[str, str]] | None = None,
    acceptance: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "taskKey": key,
        "identity": identity(index),
        "revision": revision,
        "dependsOnTaskKeys": depends or [],
        "successorTaskKeys": successors or [],
        "terminalLeaf": terminal_leaf,
        "evidence": evidence or [],
        "acceptanceEvidence": acceptance or [],
    }
    if gate is not None:
        result["gateKind"] = gate
    if mirror_of is not None:
        result["mirrorOfTaskKey"] = mirror_of
    return result


def status(
    tasks: list[dict[str, object]],
    *,
    configured: int | None = 2,
    supplied_active: int = 0,
    supplied_reserved: int = 0,
    capacity_failure: bool = False,
    generated: str | None = GENERATED,
    root_excluded: bool = True,
) -> dict[str, object]:
    capacity = (
        []
        if configured is None
        else [
            {
                "saga_id": "saga-safe",
                "configured_capacity": configured,
                "runnable_queue_count": 0,
                "active_or_reserved_count": supplied_active + supplied_reserved,
                "active_count": supplied_active,
                "reserved_setup_count": supplied_reserved,
                "outcome": "CAPACITY_FULL",
                "successor_task_id": None,
                "successor_receipted": False,
                "terminal_status": "completed",
                "clean_handback": True,
                "failure_state": (
                    "CAPACITY_INVARIANT_FAILED" if capacity_failure else None
                ),
                "evidence_refs": ["test:capacity"],
                "updated_at": GENERATED,
            }
        ]
    )
    return {
        "interface_version": "1.0",
        "ok": True,
        "operation": "status",
        "result": {
            "schema_version": "1.2",
            "revision": 12,
            "policy_revision": 1,
            "tasks": tasks,
            "rules": [],
            "capacity": capacity,
            "capacity_failure": capacity_failure,
            "duration": {
                "bucket_order": [
                    "seconds",
                    "5m",
                    "10m",
                    "15m",
                    "20m",
                    "30m",
                    "45m",
                    "60m+",
                ],
                "non_runtime_states": ["blocked", "waiting"],
                "root_excluded_from_worker_capacity": root_excluded,
                "receipt_backed_lane_counts": {"seconds": supplied_active},
                "reserved_setup_lane_counts": {"seconds": supplied_reserved},
                "freshness": {
                    "evaluated_at": generated,
                    "stale_task_count": 0,
                    "state": "EVALUATED" if generated else "UNKNOWN_CLOCK",
                },
                "calibration_groups": [],
                "minimum_completed_samples": 5,
            },
            "outbox": [],
        },
    }


def request(
    tasks: list[dict[str, object]],
    facts: list[dict[str, object]],
    **status_options: object,
) -> dict[str, object]:
    return {
        "interfaceVersion": "1.0",
        "servedAt": SERVED,
        "freshnessThresholdSeconds": 60,
        "status": status(tasks, **status_options),
        "taskFacts": facts,
    }


def baseline() -> dict[str, object]:
    done_key = PRIVATE_TASK
    waiting_key = "private-task-two"
    return request(
        [
            task(done_key, "ARCHIVE_PENDING"),
            task(waiting_key, "BLOCKED"),
        ],
        [
            fact(
                done_key,
                1,
                successors=[waiting_key],
                acceptance=[{"kind": "test", "ref": "test:acceptance-1"}],
            ),
            fact(waiting_key, 2, gate="dependency", depends=[done_key]),
        ],
    )


class ReceiptFeedTests(unittest.TestCase):
    def populate_synthetic_ledger(self, state: Path) -> dict[str, object]:
        fixture = json.loads(SYNTHETIC_STATE.read_text(encoding="utf-8"))
        common = [
            sys.executable,
            "-B",
            str(CONTROL_CLI),
            "--state-dir",
            str(state),
            "--policy-ledger",
            str(POLICY_LEDGER),
        ]
        initialized = subprocess.run(
            [*common, "init", "--now", fixture["generatedAt"]],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, initialized.returncode, initialized.stderr)
        connection = sqlite3.connect(state / "orchestrator.sqlite3")
        for index, worker in enumerate(fixture["workers"], start=1):
            block = (
                json.dumps({"classification": worker["blockClassification"]})
                if worker.get("blockClassification")
                else None
            )
            closure = (
                json.dumps({"checks": [{"result": "pass"}]})
                if worker["state"] == "ARCHIVE_PENDING"
                else None
            )
            connection.execute(
                """INSERT INTO tasks(
                  task_id,source_event_key,idempotency_key,outcome_key,
                  external_thread_id,state,priority,dependencies_json,target_json,
                  prompt_reference,policy_revision,applicable_rule_ids_json,
                  lease_epoch,fencing_token,created_at,updated_at,block_json,
                  closure_json,source
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    worker["taskKey"],
                    worker["sourceEventKey"],
                    f"fixture-idempotency-{index}",
                    worker["outcomeKey"],
                    worker.get("externalThreadKey"),
                    worker["state"],
                    100 - index,
                    json.dumps(worker["dependencies"]),
                    json.dumps(
                        {
                            "repo_alias": "fixture-repository",
                            "path": "/private/redacted-fixture-path",
                        }
                    ),
                    f"fixture-prompt-reference-{index}",
                    1,
                    "[]",
                    1,
                    index,
                    fixture["generatedAt"],
                    fixture["generatedAt"],
                    block,
                    closure,
                    "fixture",
                ),
            )
            connection.execute(
                """INSERT INTO task_timing(
                  task_id,estimate_version,estimated_bucket,current_lane,confidence,
                  task_family,tool_family,environment_class,evidence_basis_json,
                  expected_setup_seconds,expected_test_seconds,
                  expected_active_seconds,expected_external_wait_seconds,
                  heavyweight_concurrency_cap,queue_entered_at,started_at,
                  actual_json,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    worker["taskKey"],
                    1,
                    "5m",
                    "5m",
                    "low",
                    "fixture-family",
                    "fixture-tool",
                    "fixture-environment",
                    '["fixture-default"]',
                    30,
                    180,
                    210,
                    20,
                    1,
                    fixture["generatedAt"],
                    fixture["generatedAt"] if worker["state"] == "RUNNING" else None,
                    (
                        json.dumps(
                            {
                                "active_seconds": 90,
                                "external_wait_seconds": 10,
                                "first_evidence_seconds": 40,
                            }
                        )
                        if worker["state"] == "RUNNING"
                        else None
                    ),
                    fixture["generatedAt"],
                ),
            )
            if worker["state"] in {"RUNNING", "LAUNCH_PENDING"}:
                receipt = (
                    json.dumps({"external_thread_id": worker["externalThreadKey"]})
                    if worker["state"] == "RUNNING"
                    else None
                )
                connection.execute(
                    """INSERT INTO launches(
                      request_id,request_hash,task_id,envelope_json,receipt_json,issued_at
                    ) VALUES(?,?,?,?,?,?)""",
                    (
                        f"fixture-launch-{index}",
                        "a" * 64,
                        worker["taskKey"],
                        '{"delegation":"fixture-envelope"}',
                        receipt,
                        fixture["generatedAt"],
                    ),
                )
                connection.execute(
                    """INSERT INTO owner_claims(
                      claim_id,canonical_resource_key,target_json,task_id,
                      lease_epoch,fencing_token,status,acquired_at,heartbeat_at,
                      expires_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        f"fixture-claim-{index}",
                        f"fixture-resource-{index}",
                        '{"repo_alias":"fixture-repository","path":"/private/redacted-fixture-path"}',
                        worker["taskKey"],
                        1,
                        index,
                        "active",
                        fixture["generatedAt"],
                        fixture["generatedAt"],
                        "2026-07-28T15:10:00Z",
                    ),
                )
            if worker["state"] == "ARCHIVE_PENDING":
                connection.execute(
                    "INSERT INTO handbacks VALUES(?,?,?,?,?,?)",
                    (
                        "fixture-handback",
                        "b" * 64,
                        worker["taskKey"],
                        '{"disposition":"completed"}',
                        '{"accepted":true}',
                        fixture["generatedAt"],
                    ),
                )
                connection.execute(
                    """INSERT INTO capacity_sagas(
                      saga_id,task_id,configured_capacity,runnable_queue_count,
                      terminal_status,clean_handback,outcome,successor_task_id,
                      successor_receipted,evidence_refs_json,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "fixture-capacity",
                        worker["taskKey"],
                        fixture["configuredWorkers"],
                        1,
                        "completed",
                        1,
                        "SUCCESSOR_RESERVED",
                        worker["successorTaskKey"],
                        0,
                        '["test:fixture-capacity"]',
                        fixture["generatedAt"],
                        fixture["generatedAt"],
                    ),
                )
        for index, decision in enumerate(fixture["ownerGateDecisions"], start=1):
            connection.execute(
                "INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?)",
                (
                    f"fixture-decision-{index}",
                    "c" * 64,
                    "OWNER_GATE",
                    decision["decisionCode"],
                    '["fixture-rule"]',
                    "fixture explanation not exported",
                    decision["gateKey"],
                    decision["recordedAt"],
                ),
            )
        connection.commit()
        connection.close()
        return fixture

    def test_schema_and_baseline_adapter(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual("urn:pm-proxy:dashboard-receipt-feed:1.0", schema["$id"])
        feed = EXPORTER.export_feed(baseline())
        EXPORTER.validate_feed(feed)
        self.assertEqual("1.0", feed["schemaVersion"])
        self.assertEqual("current", feed["source"]["freshness"]["state"])
        self.assertEqual(5, feed["source"]["freshness"]["ageSeconds"])
        self.assertEqual(1, feed["counts"]["done"])
        self.assertEqual(1, feed["counts"]["waiting"])
        waiting = next(row for row in feed["receipts"] if row["lifecycle"] == "waiting")
        self.assertTrue(waiting["runnable"])

    def test_real_firestarter_status_response_adapts_without_private_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            common = [
                sys.executable,
                "-B",
                str(CONTROL_CLI),
                "--state-dir",
                str(state),
                "--policy-ledger",
                str(POLICY_LEDGER),
            ]
            initialized = subprocess.run(
                [*common, "init", "--now", GENERATED],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, initialized.returncode, initialized.stderr)
            observed = subprocess.run(
                [*common, "status", "--now", GENERATED],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, observed.returncode, observed.stderr)
            feed = EXPORTER.export_feed(
                {
                    "interfaceVersion": "1.0",
                    "servedAt": SERVED,
                    "freshnessThresholdSeconds": 60,
                    "status": json.loads(observed.stdout),
                    "taskFacts": [],
                }
            )
            self.assertEqual("live", feed["source"]["sourceStatus"])
            self.assertEqual("status-0", feed["source"]["sourceRevision"])
            self.assertEqual([], feed["receipts"])
            self.assertEqual(0, feed["counts"]["active"])
            self.assertEqual(0, feed["counts"]["runnable"])
            self.assertNotIn(str(state), json.dumps(feed))

    def test_stale_and_unknown_generated_time_are_not_current(self) -> None:
        stale = baseline()
        stale["servedAt"] = "2026-07-28T15:02:00Z"
        stale_feed = EXPORTER.export_feed(stale)
        self.assertEqual("stale", stale_feed["source"]["freshness"]["state"])
        self.assertEqual("degraded", stale_feed["source"]["sourceStatus"])
        unknown = baseline()
        unknown["status"]["result"]["duration"]["freshness"]["evaluated_at"] = None
        unknown_feed = EXPORTER.export_feed(unknown)
        self.assertEqual("unknown", unknown_feed["source"]["freshness"]["state"])
        self.assertIsNone(unknown_feed["source"]["generatedAt"])
        self.assertEqual("invalid", unknown_feed["source"]["sourceStatus"])

    def test_missing_capacity_and_duration_are_unavailable_not_zero(self) -> None:
        item = task("waiting-only", "BLOCKED", duration=None)
        feed = EXPORTER.export_feed(
            request([item], [fact("waiting-only", 1)], configured=None)
        )
        self.assertIsNone(feed["capacity"]["configuredWorkers"])
        self.assertEqual("unavailable", feed["capacity"]["availability"])
        self.assertIsNone(feed["counts"]["runnable"])
        receipt = feed["receipts"][0]
        self.assertIsNone(receipt["runnable"])
        for duration_metric in receipt["duration"].values():
            self.assertEqual(
                {"value": None, "availability": "unavailable"},
                duration_metric,
            )

    def test_duplicate_revision_quarantine_and_mirror_exclusion(self) -> None:
        first = task("canonical", "RUNNING")
        duplicate = task("duplicate", "RUNNING")
        first_fact = fact("canonical", 1)
        duplicate_fact = fact("duplicate", 1)
        duplicate_fact["identity"] = deepcopy(first_fact["identity"])
        conflicting = EXPORTER.export_feed(
            request(
                [first, duplicate],
                [first_fact, duplicate_fact],
                supplied_active=2,
            )
        )
        self.assertEqual([], conflicting["receipts"])
        self.assertEqual(2, conflicting["counts"]["quarantined"])
        self.assertEqual(0, conflicting["counts"]["active"])

        duplicate["state"] = "DUPLICATE_STOP"
        duplicate["canonical_external_thread_id"] = None
        duplicate_fact["mirrorOfTaskKey"] = "canonical"
        mirrored = EXPORTER.export_feed(
            request(
                [first, duplicate],
                [first_fact, duplicate_fact],
                supplied_active=1,
            )
        )
        self.assertEqual(1, mirrored["counts"]["active"])
        self.assertEqual(1, mirrored["counts"]["quarantined"])
        self.assertEqual("mirror", mirrored["quarantine"][0]["reason"])

    def test_root_exclusion_and_receipt_backing_fail_closed(self) -> None:
        root = baseline()
        root["status"]["result"]["duration"][
            "root_excluded_from_worker_capacity"
        ] = False
        with self.assertRaisesRegex(EXPORTER.ExportError, "exclude root"):
            EXPORTER.export_feed(root)
        unreceipted = task("bad-running", "RUNNING")
        unreceipted["canonical_external_thread_id"] = None
        with self.assertRaisesRegex(EXPORTER.ExportError, "canonical launch receipt"):
            EXPORTER.export_feed(
                request([unreceipted], [fact("bad-running", 1)])
            )

    def test_failed_setup_releases_reservation(self) -> None:
        failed = task("failed-setup", "FAILED")
        feed = EXPORTER.export_feed(
            request([failed], [fact("failed-setup", 1)], supplied_reserved=0)
        )
        self.assertEqual(0, feed["counts"]["setupReserved"])
        self.assertEqual(1, feed["counts"]["failed"])
        self.assertEqual(0, feed["counts"]["active"])

    def test_owner_gate_is_only_owner_action_state(self) -> None:
        blocked = task(
            "owner-gated",
            "BLOCKED",
            block={"classification": "owner_gate", "reason_code": "OWNER_GATE"},
        )
        feed = EXPORTER.export_feed(
            request([blocked], [fact("owner-gated", 1, gate="owner")])
        )
        self.assertEqual("owner-gated", feed["receipts"][0]["lifecycle"])
        self.assertEqual("owner", feed["receipts"][0]["gateKind"])
        self.assertFalse(feed["receipts"][0]["runnable"])
        bad = request([blocked], [fact("owner-gated", 1, gate="external")])
        with self.assertRaisesRegex(EXPORTER.ExportError, "owner gate"):
            EXPORTER.export_feed(bad)

    def test_dag_cycle_and_close_without_successor_fail_closed(self) -> None:
        first = task("first", "BLOCKED")
        second = task("second", "BLOCKED")
        cyclic = request(
            [first, second],
            [
                fact("first", 1, depends=["second"]),
                fact("second", 2, depends=["first"]),
            ],
        )
        with self.assertRaisesRegex(EXPORTER.ExportError, "dependency cycle"):
            EXPORTER.export_feed(cyclic)
        done = task("done", "ARCHIVE_PENDING")
        no_successor = request(
            [done],
            [
                fact(
                    "done",
                    1,
                    acceptance=[{"kind": "test", "ref": "test:accepted"}],
                )
            ],
        )
        with self.assertRaisesRegex(EXPORTER.ExportError, "requires a successor"):
            EXPORTER.export_feed(no_successor)
        leaf = no_successor
        leaf["taskFacts"][0]["terminalLeaf"] = True
        leaf["taskFacts"][0]["evidence"] = [
            {"kind": "decision", "ref": "decision:terminal-leaf"}
        ]
        self.assertEqual(1, EXPORTER.export_feed(leaf)["counts"]["done"])

    def test_supplied_count_mismatch_keeps_derived_truth(self) -> None:
        active = task("active-one", "RUNNING")
        feed = EXPORTER.export_feed(
            request([active], [fact("active-one", 1)], supplied_active=7)
        )
        self.assertEqual(1, feed["counts"]["active"])
        self.assertEqual("degraded", feed["source"]["sourceStatus"])
        self.assertIn(
            "SUPPLIED_DERIVED_MISMATCH", feed["source"]["discrepancies"]
        )

    def test_duration_projection_keeps_components_separate(self) -> None:
        duration = {
            "estimate_version": 2,
            "estimated_bucket": "10m",
            "current_lane": "10m",
            "expected_components": {
                "setup_seconds": 30,
                "test_seconds": 300,
                "remote_wait_seconds": 60,
            },
            "actual": {
                "active_seconds": 250,
                "queue_seconds": 90,
                "setup_seconds": 25,
                "tool_wait_seconds": 15,
                "external_wait_seconds": None,
                "total_wall_seconds": 380,
                "first_evidence_seconds": 80,
                "safe_close_seconds": None,
            },
        }
        active = task("duration-task", "RUNNING", duration=duration)
        feed = EXPORTER.export_feed(
            request([active], [fact("duration-task", 1)], supplied_active=1)
        )
        metrics = feed["receipts"][0]["duration"]
        self.assertEqual({"value": 330, "availability": "derived"}, metrics["estimateSeconds"])
        self.assertEqual({"value": 250, "availability": "derived"}, metrics["elapsedActiveSeconds"])
        self.assertEqual({"value": None, "availability": "unavailable"}, metrics["externalWaitSeconds"])
        self.assertEqual({"value": 80, "availability": "derived"}, metrics["firstUsefulEvidenceSeconds"])

    def test_privacy_rejection_and_output_is_fresh_projection(self) -> None:
        unsafe_refs = [
            "/private/tmp/file",
            "artifact:../secret",
            "deploy:x?token=secret",
            "user@example.com",
            "task:123e4567-e89b-12d3-a456-426614174000",
        ]
        for ref in unsafe_refs:
            with self.subTest(ref=ref):
                item = task("privacy-task", "BLOCKED")
                bad = fact(
                    "privacy-task",
                    1,
                    evidence=[{"kind": "artifact", "ref": ref}],
                )
                with self.assertRaises(EXPORTER.ExportError):
                    EXPORTER.export_feed(request([item], [bad]))
        feed_text = json.dumps(EXPORTER.export_feed(baseline()), sort_keys=True)
        self.assertNotIn(PRIVATE_TASK, feed_text)
        self.assertNotIn(PRIVATE_PATH, feed_text)
        self.assertNotIn("canonical_external_thread_id", feed_text)
        self.assertNotIn("task_id", feed_text)

    def test_cli_and_dashboard_consumer_contract(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-B", str(EXPORTER_PATH), "--request", "-"],
            cwd=ROOT,
            input=json.dumps(baseline()),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("1.0", json.loads(completed.stdout)["schemaVersion"])
        dashboard = DASHBOARD_PATH.read_text(encoding="utf-8")
        for marker in (
            'payload.schemaVersion === "1.0"',
            "generatedAt",
            "servedAt",
            "sourceStatus",
            "freshness",
            "rootExcluded",
            "setupReserved",
            "Array.isArray(payload.ownerGates)",
            'section("Owner actions (review only)", payload.ownerGates',
            "metric.availability === \"unavailable\"",
            "Quarantined mirrors and conflicts",
            "review-only",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, dashboard)
        self.assertIn("connect-src 'none'", dashboard)
        self.assertNotIn('payload.operation !== "status"', dashboard)

    def test_ledger_publication_validation_lkg_and_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state"
            output = root / "published"
            fixture = self.populate_synthetic_ledger(state)
            command = [
                sys.executable,
                "-B",
                str(EXPORTER_PATH),
                "publish-ledger",
                "--state-dir",
                str(state),
                "--output-dir",
                str(output),
                "--generated-at",
                fixture["generatedAt"],
                "--served-at",
                fixture["servedAt"],
                "--stale-threshold-seconds",
                "60",
            ]
            first = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True, check=False
            )
            self.assertEqual(0, first.returncode, first.stderr)
            published = json.loads(first.stdout)
            snapshot = output / published["snapshot"]
            self.assertEqual(
                published["sha256"],
                __import__("hashlib").sha256(snapshot.read_bytes()).hexdigest(),
            )
            self.assertEqual(0o600, os.stat(snapshot).st_mode & 0o777)
            feed = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertEqual("live", feed["source"]["sourceStatus"])
            self.assertEqual("current", feed["source"]["freshness"]["state"])
            self.assertEqual(2, feed["capacity"]["configuredWorkers"])
            self.assertEqual(1, feed["counts"]["active"])
            self.assertEqual(1, feed["counts"]["setupReserved"])
            self.assertEqual(1, feed["counts"]["waiting"])
            self.assertEqual(1, feed["counts"]["done"])
            self.assertEqual(1, len(feed["ownerGates"]))
            self.assertEqual(2, feed["ownerGates"][0]["revision"])
            serialized = json.dumps(feed, sort_keys=True)
            for forbidden in (
                "/private/redacted-fixture-path",
                "fixture-prompt-reference",
                "fixture explanation",
                "externalThreadKey",
                "task_id",
            ):
                self.assertNotIn(forbidden, serialized)
            validated = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(EXPORTER_PATH),
                    "validate-snapshot",
                    "--snapshot",
                    str(snapshot),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, validated.returncode, validated.stderr)
            self.assertEqual(published["sha256"], json.loads(validated.stdout)["sha256"])

            second_command = deepcopy(command)
            second_command[second_command.index(fixture["servedAt"])] = (
                "2026-07-28T15:02:00Z"
            )
            second = subprocess.run(
                second_command, cwd=ROOT, capture_output=True, text=True, check=False
            )
            self.assertEqual(0, second.returncode, second.stderr)
            second_result = json.loads(second.stdout)
            self.assertEqual("stale", second_result["freshness"]["state"])
            self.assertEqual("degraded", second_result["sourceStatus"])
            self.assertEqual(
                "receipt-feed-previous.json", second_result["previousPointer"]
            )
            rollback = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(EXPORTER_PATH),
                    "rollback",
                    "--output-dir",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, rollback.returncode, rollback.stderr)
            self.assertEqual(published["sha256"], json.loads(rollback.stdout)["sha256"])
            current = json.loads(
                (output / "receipt-feed-current.json").read_text(encoding="utf-8")
            )
            self.assertEqual(published["sha256"], current["sha256"])

    def test_invalid_ledger_export_keeps_current_lkg(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state"
            output = root / "published"
            fixture = self.populate_synthetic_ledger(state)
            arguments = [
                sys.executable,
                "-B",
                str(EXPORTER_PATH),
                "publish-ledger",
                "--state-dir",
                str(state),
                "--output-dir",
                str(output),
                "--generated-at",
                fixture["generatedAt"],
                "--served-at",
                fixture["servedAt"],
            ]
            first = subprocess.run(
                arguments, cwd=ROOT, capture_output=True, text=True, check=False
            )
            self.assertEqual(0, first.returncode, first.stderr)
            before = (output / "receipt-feed-current.json").read_bytes()
            connection = sqlite3.connect(state / "orchestrator.sqlite3")
            connection.execute(
                "UPDATE tasks SET source_event_key='/private/raw-source' WHERE task_id='fixture-active'"
            )
            connection.commit()
            connection.close()
            failed = subprocess.run(
                arguments, cwd=ROOT, capture_output=True, text=True, check=False
            )
            self.assertEqual(2, failed.returncode)
            self.assertEqual("PRIVACY_REJECTED", json.loads(failed.stderr)["error"]["code"])
            self.assertEqual(
                before, (output / "receipt-feed-current.json").read_bytes()
            )


if __name__ == "__main__":
    unittest.main()
