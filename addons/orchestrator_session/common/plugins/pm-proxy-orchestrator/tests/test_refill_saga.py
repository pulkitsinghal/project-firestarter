from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests.support import (
    BRIDGE,
    PLUGIN_ROOT,
    config_verified_runtime_attestation,
    handback_request,
    iso,
    launch_request,
    make_fake_install,
    private_temp,
    recycle_request,
    refill_request,
    write_json,
)
from tests.task_tool_stub import SyntheticTaskTool


REFILL = PLUGIN_ROOT / "skills/pm-proxy-orchestrator/scripts/refill_saga.py"


class RefillSagaTestCase(unittest.TestCase):
    def setUp(self):
        self.root = private_temp("pm-proxy-refill-")
        self.cli = make_fake_install(self.root)
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.runtime_attestation = write_json(
            self.root / "runtime-attestation.json",
            config_verified_runtime_attestation(),
        )

    def run_script(self, script: Path, *args: str, mode: str | None = None):
        environment = os.environ.copy()
        if mode is not None:
            environment["FAKE_CLI_MODE"] = mode
        return subprocess.run(
            [
                sys.executable,
                str(script),
                "--cli",
                str(self.cli),
                "--state-dir",
                str(self.state),
                *args,
            ],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

    def start_predecessor(self, suffix: str = "") -> Path:
        task_id = "task-predecessor" + suffix
        recycle = write_json(
            self.root / f"predecessor-recycle{suffix}.json",
            recycle_request(request_id="predecessor-recycle" + suffix),
        )
        launch = write_json(
            self.root / f"predecessor-launch{suffix}.json",
            launch_request(
                task_id=task_id,
                source_event_key="predecessor-source" + suffix,
                outcome_key="predecessor-outcome" + suffix,
                idempotency_key="predecessor-idem" + suffix,
            ),
        )
        ticket = self.state / f"{task_id}.ticket.json"
        prepared = self.run_script(
            BRIDGE,
            "prepare-launch",
            "--recycle-request",
            str(recycle),
            "--launch-request",
            str(launch),
            "--ticket",
            str(ticket),
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        receipt = self.run_script(
            BRIDGE,
            "record-launch-receipt",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            "thread-predecessor" + suffix,
            "--runtime-attestation",
            str(self.runtime_attestation),
            "--request-id",
            "predecessor-receipt" + suffix,
            "--now",
            iso(minutes=1),
        )
        self.assertEqual(receipt.returncode, 0, receipt.stderr)
        return ticket

    def set_control_schema_hold(
        self,
        ticket_path: Path,
        *,
        fence: int,
        replay_target: str = "completed_local_only",
        hold_fence: int | None = None,
    ) -> None:
        ticket = json.loads(ticket_path.read_text(encoding="utf-8"))
        ticket["fencing_token"] = fence
        ticket_path.write_text(json.dumps(ticket, sort_keys=True) + "\n", encoding="utf-8")
        state_path = self.state / "fake-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        task = state["tasks"][ticket["task_id"]]
        task["fencing_token"] = fence
        task["claim_fencing_token"] = fence
        task["lifecycle"] = {
            "task_id": ticket["task_id"],
            "lifecycle_state": "CONTROL_SCHEMA_HOLD",
        }
        task["control_schema_hold"] = {
            "hold_state": "CONTROL_SCHEMA_HOLD",
            "ticket_id": ticket["source_event_key"],
            "task_id": ticket["task_id"],
            "external_thread_id": ticket["receipt"]["external_thread_id"],
            "policy_snapshot_revision": ticket["policy_snapshot_revision"],
            "lease_epoch": ticket["lease_epoch"],
            "fencing_token": fence if hold_fence is None else hold_fence,
            "replay_target": replay_target,
        }
        state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")

    def set_terminal_evidence(
        self,
        ticket_path: Path,
        *,
        fence: int,
        lifecycle_state: str = "INTERRUPT_REQUIRED",
        worker_status: str,
        completion_signals: list[str] | None = None,
        required_action: str = "TERMINALIZE",
    ) -> None:
        ticket = json.loads(ticket_path.read_text(encoding="utf-8"))
        ticket["fencing_token"] = fence
        ticket_path.write_text(json.dumps(ticket, sort_keys=True) + "\n", encoding="utf-8")
        state_path = self.state / "fake-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        task = state["tasks"][ticket["task_id"]]
        task["fencing_token"] = fence
        task["claim_fencing_token"] = fence
        task["lifecycle"] = {
            "task_id": ticket["task_id"],
            "lifecycle_state": lifecycle_state,
            "worker_status": worker_status,
            "completion_signals": (
                ["worker-final"]
                if completion_signals is None
                else completion_signals
            ),
            "required_action": required_action,
        }
        task["control_schema_hold"] = None
        state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")

    def local_only_handback(
        self,
        ticket_path: Path,
        *,
        handback_id: str,
        now: str,
        disposition: str = "completed_local_only",
    ) -> Path:
        ticket = json.loads(ticket_path.read_text(encoding="utf-8"))
        value = handback_request(
            task_id=ticket["task_id"],
            handback_id=handback_id,
            now=now,
        )
        for key in (
            "policy_snapshot_revision",
            "lease_epoch",
            "fencing_token",
        ):
            value[key] = ticket[key]
        value["disposition"] = disposition
        value["exact_refs"] = {
            "base_sha": "a" * 40,
            "candidate_sha": (
                None if disposition == "completed_local_artifact" else "b" * 40
            ),
            "pr_url": None,
            "merge_sha": None,
            "default_sha": None,
        }
        value["external_delivery"] = "not_performed"
        if disposition == "completed_local_artifact":
            value["local_artifact"] = {
                "algorithm": "sha256",
                "entries": [
                    {
                        "relative_path": "synthetic/report.json",
                        "transition": "created",
                        "before_sha256": None,
                        "after_sha256": "c" * 64,
                    }
                ],
                "manifest_sha256": "d" * 64,
                "rollback": {
                    "strategy": "restore_base",
                    "evidence_ref": "synthetic-rollback",
                },
            }
        value["resources"] = [
            {
                "id": ticket["owner_claim_id"],
                "disposition": "removed",
                "reason": "synthetic fenced owner claim released",
                "bytes": 0,
            }
        ]
        return write_json(self.root / f"{handback_id}.json", value)

    def close_for_legacy_archive(self, ticket_path: Path, suffix: str) -> Path:
        ticket = json.loads(ticket_path.read_text(encoding="utf-8"))
        self.set_terminal_evidence(
            ticket_path,
            fence=ticket["fencing_token"],
            lifecycle_state="COMPLETED",
            worker_status="completed",
            required_action="ARCHIVE",
        )
        ticket = json.loads(ticket_path.read_text(encoding="utf-8"))
        handback_value = handback_request(
            task_id=ticket["task_id"],
            handback_id=f"legacy-{suffix}",
            now=iso(minutes=2),
        )
        for key in ("policy_snapshot_revision", "lease_epoch", "fencing_token"):
            handback_value[key] = ticket[key]
        handback_value["resources"] = [
            {
                "id": ticket["owner_claim_id"],
                "disposition": "removed",
                "reason": "synthetic legacy owner claim released",
                "bytes": 0,
            }
        ]
        handback = write_json(
            self.root / f"legacy-{suffix}-handback.json", handback_value
        )
        refill = write_json(
            self.root / f"legacy-{suffix}-refill.json",
            refill_request(request_id=f"legacy-{suffix}", now=iso(minutes=2)),
        )
        closed = self.run_script(
            REFILL,
            "close-and-refill",
            "--predecessor-ticket",
            str(ticket_path),
            "--handback-request",
            str(handback),
            "--refill-request",
            str(refill),
        )
        self.assertEqual(0, closed.returncode, closed.stderr)
        state = json.loads((self.state / "fake-state.json").read_text(encoding="utf-8"))
        state["schema_version"] = "1.4"
        (self.state / "fake-state.json").write_text(
            json.dumps(state, sort_keys=True) + "\n", encoding="utf-8"
        )
        task = state["tasks"][ticket["task_id"]]
        archive = next(
            item
            for item in state["outbox"].values()
            if item["task_id"] == ticket["task_id"]
            and item["kind"] == "ARCHIVE_THREAD"
        )
        request = {
            "interface_version": "1.0",
            "request_id": f"legacy-reconcile-{suffix}",
            "task_id": ticket["task_id"],
            "expected_source_event_key": ticket["source_event_key"],
            "external_thread_id": ticket["receipt"]["external_thread_id"],
            "expected_state_revision": state["revision"],
            "policy_snapshot_revision": ticket["policy_snapshot_revision"],
            "lease_epoch": ticket["lease_epoch"],
            "fencing_token": ticket["fencing_token"],
            "owner_claim_id": task["owner_claim_id"],
            "expected_archive_outbox_id": archive["outbox_id"],
            "external_archive_proof": {
                "external_thread_id": ticket["receipt"]["external_thread_id"],
                "state": "archived",
                "observation_source": "external-task-api",
                "observed_at": iso(minutes=4),
                "evidence_refs": [f"external-observation-{suffix}"],
            },
            "now": iso(minutes=5),
        }
        return write_json(self.root / f"legacy-{suffix}-request.json", request)

    def test_interrupted_notloaded_clean_handback_refills_once_without_owner_prompt(self):
        predecessor = self.start_predecessor()
        successor = launch_request(
            task_id="task-successor",
            source_event_key="successor-source",
            outcome_key="successor-outcome",
            idempotency_key="successor-idem",
            prompt="SYNTHETIC_SUCCESSOR_VERBATIM",
            now=iso(minutes=2),
            lease_expires_at=iso(minutes=32),
        )
        handback = write_json(
            self.root / "handback.json",
            handback_request(
                task_id="task-predecessor",
                handback_id="missed-closeout",
                now=iso(minutes=2),
            ),
        )
        refill = write_json(
            self.root / "refill.json",
            refill_request(
                candidates=[successor],
                request_id="missed-closeout",
                status="interrupted/notLoaded",
                valid_clean_handback=True,
            ),
        )
        closed = self.run_script(
            REFILL,
            "close-and-refill",
            "--predecessor-ticket",
            str(predecessor),
            "--handback-request",
            str(handback),
            "--refill-request",
            str(refill),
        )
        self.assertEqual(closed.returncode, 0, closed.stderr)
        result = json.loads(closed.stdout)["result"]
        self.assertTrue(result["capacity_released"])
        self.assertEqual(result["outcome"], "SUCCESSOR_RESERVED")
        self.assertEqual(len(result["launches"]), 1)
        self.assertFalse(result["slot_truth"]["failure_state"])
        self.assertEqual(result["slot_truth"]["active_or_reserved_count"], 1)
        self.assertEqual(result["slot_truth"]["runnable_task_ids"], [])

        premature_archive = self.run_script(
            BRIDGE,
            "record-archive-receipt",
            "--ticket",
            str(predecessor),
            "--request-id",
            "premature-archive",
            "--now",
            iso(minutes=2, seconds=30),
        )
        self.assertEqual(premature_archive.returncode, 2)
        self.assertEqual(
            json.loads(premature_archive.stderr)["error"]["code"],
            "CAPACITY_REFILL_PENDING",
        )

        tool = SyntheticTaskTool()
        launch = result["launches"][0]
        external = tool.create(
            prompt=launch["prompt"],
            idempotency_key=launch["outbox"]["outbox_id"],
        )
        self.assertEqual(len(tool.calls), 1)
        self.assertTrue(tool.calls[0]["prompt"].startswith("SYNTHETIC_SUCCESSOR_VERBATIM"))
        receipt = self.run_script(
            REFILL,
            "record-refill-receipt",
            "--saga-id",
            "missed-closeout",
            "--task-id",
            "task-successor",
            "--external-thread-id",
            external,
            "--runtime-attestation",
            str(self.runtime_attestation),
            "--request-id",
            "successor-receipt",
            "--now",
            iso(minutes=3),
        )
        self.assertEqual(receipt.returncode, 0, receipt.stderr)
        self.assertEqual(json.loads(receipt.stdout)["result"]["saga_outcome"], "REFILL_SATISFIED")
        replayed_receipt = self.run_script(
            REFILL,
            "record-refill-receipt",
            "--saga-id",
            "missed-closeout",
            "--task-id",
            "task-successor",
            "--external-thread-id",
            external,
            "--runtime-attestation",
            str(self.runtime_attestation),
            "--request-id",
            "successor-receipt",
            "--now",
            iso(minutes=3),
        )
        self.assertEqual(0, replayed_receipt.returncode, replayed_receipt.stderr)
        self.assertTrue(json.loads(replayed_receipt.stdout)["result"]["replayed"])

        ledger_text = (self.state / "pm-proxy-refill-ledger.json").read_text(encoding="utf-8")
        ledger = json.loads(ledger_text)
        events = ledger["sagas"]["missed-closeout"]["events"]
        self.assertIn("CAPACITY_RELEASED", [item["event"] for item in events])
        self.assertIn("SUCCESSOR_RECEIPTED", [item["event"] for item in events])
        self.assertNotIn("SYNTHETIC_SUCCESSOR_VERBATIM", ledger_text)
        self.assertNotIn("prompt_hash", ledger_text)

        archived = self.run_script(
            BRIDGE,
            "record-archive-receipt",
            "--ticket",
            str(predecessor),
            "--request-id",
            "archive-predecessor",
            "--now",
            iso(minutes=4),
        )
        self.assertEqual(archived.returncode, 0, archived.stderr)

    def test_stream_recorder_fence_38_expired_hold_replays_local_only_to_empty(self):
        predecessor = self.start_predecessor()
        self.set_control_schema_hold(predecessor, fence=38)
        handback = self.local_only_handback(
            predecessor,
            handback_id="stream-recorder-fence-38",
            now=iso(minutes=31),
        )
        refill = write_json(
            self.root / "stream-recorder-refill.json",
            refill_request(
                request_id="stream-recorder-fence-38",
                now=iso(minutes=31),
            ),
        )

        closed = self.run_script(
            REFILL,
            "close-and-refill",
            "--predecessor-ticket",
            str(predecessor),
            "--handback-request",
            str(handback),
            "--refill-request",
            str(refill),
        )
        self.assertEqual(0, closed.returncode, closed.stderr)
        result = json.loads(closed.stdout)["result"]
        self.assertEqual("EMPTY", result["outcome"])
        self.assertTrue(result["capacity_released"])
        self.assertEqual([], result["launches"])
        state = json.loads((self.state / "fake-state.json").read_text(encoding="utf-8"))
        task = state["tasks"]["task-predecessor"]
        self.assertEqual("ARCHIVE_PENDING", task["state"])
        self.assertIsNone(task["control_schema_hold"])
        self.assertEqual("COMPLETED", task["lifecycle"]["lifecycle_state"])
        saga = json.loads(
            (self.state / "pm-proxy-refill-ledger.json").read_text(encoding="utf-8")
        )["sagas"]["stream-recorder-fence-38"]
        events = [item["event"] for item in saga["events"]]
        self.assertEqual("CAPACITY_RELEASED", events[0])
        self.assertIn("EMPTY", events)
        archive = (
            "record-archive-receipt",
            "--ticket",
            str(predecessor),
            "--request-id",
            "stream-recorder-fence-38-archive",
            "--now",
            iso(minutes=32),
        )
        archived = self.run_script(BRIDGE, *archive)
        self.assertEqual(0, archived.returncode, archived.stderr)
        receipt_at = json.loads(predecessor.read_text(encoding="utf-8"))[
            "handback"
        ]["archive_receipt_at"]
        replayed = self.run_script(BRIDGE, *archive)
        self.assertEqual(0, replayed.returncode, replayed.stderr)
        self.assertEqual(
            receipt_at,
            json.loads(predecessor.read_text(encoding="utf-8"))["handback"][
                "archive_receipt_at"
            ],
        )

    def test_predecessor_006_archive_uses_authoritative_replacement_008_receipt(self):
        predecessor = self.start_predecessor("-006")
        predecessor_ticket = json.loads(predecessor.read_text(encoding="utf-8"))
        self.set_terminal_evidence(
            predecessor,
            fence=predecessor_ticket["fencing_token"],
            worker_status="completed",
        )
        successor_007 = launch_request(
            task_id="task-successor-007",
            source_event_key="successor-007-source",
            outcome_key="successor-007-outcome",
            idempotency_key="successor-007-idem",
            now=iso(minutes=2),
            lease_expires_at=iso(minutes=32),
        )
        handback = write_json(
            self.root / "predecessor-006-handback.json",
            handback_request(
                task_id="task-predecessor-006",
                handback_id="predecessor-006",
                now=iso(minutes=2),
            ),
        )
        refill = write_json(
            self.root / "predecessor-006-refill.json",
            refill_request(
                candidates=[successor_007],
                request_id="predecessor-006",
                now=iso(minutes=2),
                capacity=1,
            ),
        )
        closed = self.run_script(
            REFILL,
            "close-and-refill",
            "--predecessor-ticket",
            str(predecessor),
            "--handback-request",
            str(handback),
            "--refill-request",
            str(refill),
        )
        self.assertEqual(0, closed.returncode, closed.stderr)
        self.assertEqual(
            "SUCCESSOR_RESERVED",
            json.loads(closed.stdout)["result"]["outcome"],
        )

        state_path = self.state / "fake-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["tasks"]["task-predecessor-006"][
            "terminal_disposition"
        ] = "superseded"
        failed = state["tasks"]["task-successor-007"]
        failed["state"] = "FAILED"
        failed["owner_claim_status"] = "released"
        failed_outbox = next(
            item
            for item in state["outbox"].values()
            if item["task_id"] == "task-successor-007"
            and item["kind"] == "CREATE_THREAD"
        )
        failed_outbox["state"] = "poisoned"
        replacement = json.loads(json.dumps(failed))
        replacement.update(
            {
                "task_id": "task-successor-008",
                "source_event_key": "successor-008-source",
                "outcome_key": "successor-008-outcome",
                "idempotency_key": "successor-008-idem",
                "state": "ARCHIVED",
                "fencing_token": 8,
                "external_thread_id": "thread-successor-008",
                "receipt_external_thread_id": "thread-successor-008",
                "owner_claim_id": "claim-task-successor-008",
                "owner_claim_status": "released",
                "claim_fencing_token": 8,
                "terminal_disposition": "completed",
                "lifecycle": {
                    "task_id": "task-successor-008",
                    "lifecycle_state": "COMPLETED",
                    "worker_status": "completed",
                    "required_action": "ARCHIVE",
                },
            }
        )
        state["tasks"]["task-successor-008"] = replacement
        state["outbox"]["create-task-successor-008"] = {
            "outbox_id": "create-task-successor-008",
            "kind": "CREATE_THREAD",
            "task_id": "task-successor-008",
            "state": "completed",
            "created_at": iso(minutes=3),
            "updated_at": iso(minutes=3),
        }
        state["outbox"]["archive-task-successor-008"] = {
            "outbox_id": "archive-task-successor-008",
            "kind": "ARCHIVE_THREAD",
            "task_id": "task-successor-008",
            "state": "completed",
            "created_at": iso(minutes=3),
            "updated_at": iso(minutes=3),
        }
        state["capacity"] = [
            {
                "saga_id": "predecessor-006",
                "outcome": "SUCCESSOR_RECEIPTED",
                "successor_task_id": "task-successor-008",
                "successor_receipted": True,
                "clean_handback": True,
                "failure_state": "CAPACITY_INVARIANT_FAILED",
            }
        ]
        state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")

        canonical = json.loads(json.dumps(state))
        state_mutations = {
            "saga-identity": lambda changed: changed["capacity"][0].__setitem__(
                "saga_id", "different-saga"
            ),
            "reserved-successor-not-failed": lambda changed: changed["tasks"][
                "task-successor-007"
            ].__setitem__("state", "LAUNCH_PENDING"),
            "reserved-outbox-not-poisoned": lambda changed: next(
                item
                for item in changed["outbox"].values()
                if item["task_id"] == "task-successor-007"
                and item["kind"] == "CREATE_THREAD"
            ).__setitem__("state", "pending"),
            "replacement-unreceipted": lambda changed: changed["tasks"][
                "task-successor-008"
            ].__setitem__("receipt_external_thread_id", None),
            "replacement-claim-active": lambda changed: changed["tasks"][
                "task-successor-008"
            ].__setitem__("owner_claim_status", "active"),
            "replacement-terminal-evidence-missing": lambda changed: changed[
                "tasks"
            ]["task-successor-008"].__setitem__("lifecycle", None),
            "replacement-create-pending": lambda changed: changed["outbox"][
                "create-task-successor-008"
            ].__setitem__("state", "pending"),
            "unknown-capacity-failure": lambda changed: changed["capacity"][
                0
            ].__setitem__("failure_state", "UNKNOWN_FAILURE"),
        }
        for label, mutate in state_mutations.items():
            with self.subTest(mismatch=label):
                changed = json.loads(json.dumps(canonical))
                mutate(changed)
                state_path.write_text(
                    json.dumps(changed, sort_keys=True) + "\n", encoding="utf-8"
                )
                rejected = self.run_script(
                    BRIDGE,
                    "record-archive-receipt",
                    "--ticket",
                    str(predecessor),
                    "--request-id",
                    f"predecessor-006-reject-{label}",
                    "--now",
                    iso(minutes=4),
                )
                self.assertEqual(2, rejected.returncode, rejected.stderr)
                self.assertEqual(
                    "CAPACITY_REFILL_PENDING",
                    json.loads(rejected.stderr)["error"]["code"],
                )

        state_path.write_text(
            json.dumps(canonical, sort_keys=True) + "\n", encoding="utf-8"
        )

        archived = self.run_script(
            BRIDGE,
            "record-archive-receipt",
            "--ticket",
            str(predecessor),
            "--request-id",
            "predecessor-006-archive-after-replacement-008",
            "--now",
            iso(minutes=4),
        )
        self.assertEqual(0, archived.returncode, archived.stderr)

    def test_screen_sanitizer_fence_41_expired_terminal_evidence_replays_artifact(self):
        predecessor = self.start_predecessor("-screen-sanitizer")
        self.set_terminal_evidence(
            predecessor,
            fence=41,
            worker_status="completed",
        )
        handback = self.local_only_handback(
            predecessor,
            handback_id="screen-sanitizer-fence-41",
            now=iso(minutes=31),
            disposition="completed_local_artifact",
        )
        refill = write_json(
            self.root / "screen-sanitizer-fence-41-refill.json",
            refill_request(
                request_id="screen-sanitizer-fence-41",
                now=iso(minutes=31),
            ),
        )

        closed = self.run_script(
            REFILL,
            "close-and-refill",
            "--predecessor-ticket",
            str(predecessor),
            "--handback-request",
            str(handback),
            "--refill-request",
            str(refill),
        )
        self.assertEqual(0, closed.returncode, closed.stderr)
        self.assertEqual("EMPTY", json.loads(closed.stdout)["result"]["outcome"])
        state = json.loads((self.state / "fake-state.json").read_text(encoding="utf-8"))
        self.assertEqual(
            "ARCHIVE_PENDING",
            state["tasks"]["task-predecessor-screen-sanitizer"]["state"],
        )
        archived = self.run_script(
            BRIDGE,
            "record-archive-receipt",
            "--ticket",
            str(predecessor),
            "--request-id",
            "screen-sanitizer-fence-41-archive",
            "--now",
            iso(minutes=32),
        )
        self.assertEqual(0, archived.returncode, archived.stderr)

    def test_screenbench_fence_42_expired_waiting_terminal_evidence_closes_empty(self):
        predecessor = self.start_predecessor("-screenbench")
        self.set_terminal_evidence(
            predecessor,
            fence=42,
            worker_status="waiting",
        )
        handback = self.local_only_handback(
            predecessor,
            handback_id="screenbench-fence-42",
            now=iso(minutes=31),
        )
        refill = write_json(
            self.root / "screenbench-fence-42-refill.json",
            refill_request(
                request_id="screenbench-fence-42",
                now=iso(minutes=31),
            ),
        )

        closed = self.run_script(
            REFILL,
            "close-and-refill",
            "--predecessor-ticket",
            str(predecessor),
            "--handback-request",
            str(handback),
            "--refill-request",
            str(refill),
        )
        self.assertEqual(0, closed.returncode, closed.stderr)
        result = json.loads(closed.stdout)["result"]
        self.assertEqual("EMPTY", result["outcome"])
        self.assertTrue(result["capacity_released"])
        self.assertEqual([], result["launches"])

    def test_expired_completed_archive_admits_exact_terminal_empty_refill(self):
        predecessor = self.start_predecessor("-completed-archive")
        ticket = json.loads(predecessor.read_text(encoding="utf-8"))
        self.set_terminal_evidence(
            predecessor,
            fence=ticket["fencing_token"],
            worker_status="completed",
        )
        handback_value = handback_request(
            task_id=ticket["task_id"],
            handback_id="completed-archive",
            now=iso(minutes=2),
        )
        for key in (
            "policy_snapshot_revision",
            "lease_epoch",
            "fencing_token",
        ):
            handback_value[key] = ticket[key]
        handback_value["resources"] = [
            {
                "id": ticket["owner_claim_id"],
                "disposition": "removed",
                "reason": "synthetic fenced owner claim released",
                "bytes": 0,
            }
        ]
        handback = write_json(
            self.root / "completed-archive-handback.json",
            handback_value,
        )
        refill = write_json(
            self.root / "completed-archive-refill.json",
            refill_request(
                request_id="completed-archive",
                now=iso(minutes=2),
            ),
        )
        closed = self.run_script(
            REFILL,
            "close-and-refill",
            "--predecessor-ticket",
            str(predecessor),
            "--handback-request",
            str(handback),
            "--refill-request",
            str(refill),
        )
        self.assertEqual(0, closed.returncode, closed.stderr)
        self.assertEqual("EMPTY", json.loads(closed.stdout)["result"]["outcome"])

        archived = self.run_script(
            BRIDGE,
            "record-archive-receipt",
            "--ticket",
            str(predecessor),
            "--request-id",
            "completed-archive-receipt",
            "--now",
            iso(minutes=31),
        )
        self.assertEqual(0, archived.returncode, archived.stderr)

    def test_legacy_archive_reconciliation_requires_missing_ticket_and_replays(self):
        predecessor = self.start_predecessor("-legacy-route")
        request = self.close_for_legacy_archive(predecessor, "route")
        present = self.run_script(
            BRIDGE,
            "reconcile-legacy-archive",
            "--request",
            str(request),
        )
        self.assertEqual(3, present.returncode, present.stderr)
        self.assertEqual(
            "LEGACY_TICKET_PRESENT",
            json.loads(present.stderr)["error"]["code"],
        )

        predecessor.unlink()
        reconciled = self.run_script(
            BRIDGE,
            "reconcile-legacy-archive",
            "--request",
            str(request),
        )
        self.assertEqual(0, reconciled.returncode, reconciled.stderr)
        result = json.loads(reconciled.stdout)["result"]
        self.assertEqual("ARCHIVED", result["state"])
        self.assertEqual("missing", result["transport_ticket_state"])
        self.assertFalse(result["replayed"])

        replayed = self.run_script(
            BRIDGE,
            "reconcile-legacy-archive",
            "--request",
            str(request),
        )
        self.assertEqual(0, replayed.returncode, replayed.stderr)
        self.assertTrue(json.loads(replayed.stdout)["result"]["replayed"])

    def test_stale_present_archive_reconciliation_commits_then_unlinks_and_replays(self):
        predecessor = self.start_predecessor("-stale-present-route")
        request = self.close_for_legacy_archive(predecessor, "stale-present-route")
        state_path = self.state / "fake-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["tasks"]["task-predecessor-stale-present-route"][
            "terminal_disposition"
        ] = "failed"
        state_path.write_text(
            json.dumps(state, sort_keys=True) + "\n", encoding="utf-8"
        )

        reconciled = self.run_script(
            BRIDGE,
            "reconcile-stale-present-archive",
            "--request",
            str(request),
        )
        self.assertEqual(0, reconciled.returncode, reconciled.stderr)
        result = json.loads(reconciled.stdout)["result"]
        self.assertEqual("ARCHIVED", result["state"])
        self.assertEqual("RECEIPT_STALE_TERMINAL", result["reconciliation_class"])
        self.assertEqual("completed", result["transport_ticket_cleanup_state"])
        self.assertFalse(result["replayed"])
        self.assertFalse(predecessor.exists())

        replayed = self.run_script(
            BRIDGE,
            "reconcile-stale-present-archive",
            "--request",
            str(request),
        )
        self.assertEqual(0, replayed.returncode, replayed.stderr)
        replay_result = json.loads(replayed.stdout)["result"]
        self.assertTrue(replay_result["replayed"])
        self.assertEqual("completed", replay_result["transport_ticket_cleanup_state"])
        self.assertFalse(predecessor.exists())

    def test_legacy_archive_reconciliation_rejects_mismatched_and_unsafe_tickets(self):
        predecessor = self.start_predecessor("-legacy-mismatch")
        request = self.close_for_legacy_archive(predecessor, "mismatch")
        ticket = json.loads(predecessor.read_text(encoding="utf-8"))
        ticket["receipt"]["external_thread_id"] = "different-external-task"
        predecessor.write_text(
            json.dumps(ticket, sort_keys=True) + "\n", encoding="utf-8"
        )
        mismatched = self.run_script(
            BRIDGE,
            "reconcile-legacy-archive",
            "--request",
            str(request),
        )
        self.assertEqual(3, mismatched.returncode, mismatched.stderr)
        self.assertEqual(
            "LEGACY_TICKET_IDENTITY_MISMATCH",
            json.loads(mismatched.stderr)["error"]["code"],
        )

        predecessor.unlink()
        unsafe = self.state / "unsafe-legacy.ticket.json"
        unsafe.symlink_to(request)
        denied = self.run_script(
            BRIDGE,
            "reconcile-legacy-archive",
            "--request",
            str(request),
        )
        self.assertEqual(4, denied.returncode, denied.stderr)
        self.assertEqual(
            "LEGACY_TICKET_AUTHORITY_UNSAFE",
            json.loads(denied.stderr)["error"]["code"],
        )
        state = json.loads((self.state / "fake-state.json").read_text(encoding="utf-8"))
        self.assertEqual(
            "ARCHIVE_PENDING",
            state["tasks"]["task-predecessor-legacy-mismatch"]["state"],
        )

    def test_expired_archive_admission_mismatches_and_incomplete_sagas_fail_closed(self):
        predecessor = self.start_predecessor("-archive-negative")
        ordinary_archive = self.run_script(
            BRIDGE,
            "record-archive-receipt",
            "--ticket",
            str(predecessor),
            "--request-id",
            "ordinary-expired-archive",
            "--now",
            iso(minutes=31),
        )
        self.assertEqual(2, ordinary_archive.returncode)
        self.assertEqual(
            "RECEIPT_STALE",
            json.loads(ordinary_archive.stderr)["error"]["code"],
        )

        ticket = json.loads(predecessor.read_text(encoding="utf-8"))
        self.set_terminal_evidence(
            predecessor,
            fence=ticket["fencing_token"],
            worker_status="waiting",
        )
        handback = self.local_only_handback(
            predecessor,
            handback_id="archive-negative",
            now=iso(minutes=31),
        )
        refill = write_json(
            self.root / "archive-negative-refill.json",
            refill_request(request_id="archive-negative", now=iso(minutes=31)),
        )
        closed = self.run_script(
            REFILL,
            "close-and-refill",
            "--predecessor-ticket",
            str(predecessor),
            "--handback-request",
            str(handback),
            "--refill-request",
            str(refill),
        )
        self.assertEqual(0, closed.returncode, closed.stderr)
        state_path = self.state / "fake-state.json"
        ledger_path = self.state / "pm-proxy-refill-ledger.json"
        canonical_state = json.loads(state_path.read_text(encoding="utf-8"))
        canonical_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        task_id = ticket["task_id"]

        state_mutations = {
            "ticket": lambda task, state: task.__setitem__(
                "source_event_key", "different-ticket"
            ),
            "external": lambda task, state: task.__setitem__(
                "external_thread_id", "different-thread"
            ),
            "policy": lambda task, state: task.__setitem__(
                "policy_snapshot_revision", task["policy_snapshot_revision"] + 1
            ),
            "lease": lambda task, state: task.__setitem__(
                "lease_epoch", task["lease_epoch"] + 1
            ),
            "fence": lambda task, state: task.__setitem__(
                "fencing_token", task["fencing_token"] + 1
            ),
            "claim": lambda task, state: task.__setitem__(
                "owner_claim_status", "active"
            ),
            "lifecycle": lambda task, state: task["lifecycle"].__setitem__(
                "required_action", "TERMINALIZE"
            ),
            "disposition": lambda task, state: task.__setitem__(
                "terminal_disposition", "unknown-terminal-disposition"
            ),
            "superseded-without-replacement": lambda task, state: task.__setitem__(
                "terminal_disposition", "superseded"
            ),
            "outbox": lambda task, state: next(
                item
                for item in state["outbox"].values()
                if item["task_id"] == task_id and item["kind"] == "ARCHIVE_THREAD"
            ).__setitem__("state", "completed"),
        }
        for label, mutate in state_mutations.items():
            with self.subTest(mismatch=label):
                changed = json.loads(json.dumps(canonical_state))
                mutate(changed["tasks"][task_id], changed)
                state_path.write_text(
                    json.dumps(changed, sort_keys=True) + "\n", encoding="utf-8"
                )
                rejected = self.run_script(
                    BRIDGE,
                    "record-archive-receipt",
                    "--ticket",
                    str(predecessor),
                    "--request-id",
                    f"archive-negative-{label}",
                    "--now",
                    iso(minutes=32),
                )
                self.assertEqual(2, rejected.returncode, rejected.stderr)
                self.assertEqual(
                    "RECEIPT_STALE",
                    json.loads(rejected.stderr)["error"]["code"],
                )

        state_path.write_text(
            json.dumps(canonical_state, sort_keys=True) + "\n", encoding="utf-8"
        )
        for label, outcome in (
            ("missing", None),
            ("nonterminal", "STARTED"),
            ("pending-successor", "SUCCESSOR_RESERVED"),
        ):
            with self.subTest(saga=label):
                changed = json.loads(json.dumps(canonical_ledger))
                if outcome is None:
                    changed["sagas"] = {}
                    expected = "CAPACITY_SAGA_MISSING"
                else:
                    changed["sagas"]["archive-negative"]["outcome"] = outcome
                    expected = "CAPACITY_REFILL_PENDING"
                ledger_path.write_text(
                    json.dumps(changed, sort_keys=True) + "\n", encoding="utf-8"
                )
                rejected = self.run_script(
                    BRIDGE,
                    "record-archive-receipt",
                    "--ticket",
                    str(predecessor),
                    "--request-id",
                    f"archive-negative-saga-{label}",
                    "--now",
                    iso(minutes=32),
                )
                self.assertEqual(2, rejected.returncode, rejected.stderr)
                self.assertEqual(
                    expected,
                    json.loads(rejected.stderr)["error"]["code"],
                )
        ledger_path.write_text(
            json.dumps(canonical_ledger, sort_keys=True) + "\n", encoding="utf-8"
        )

    def test_expired_completion_candidate_request_handback_replays_local_only(self):
        predecessor = self.start_predecessor("-completion-candidate")
        self.set_terminal_evidence(
            predecessor,
            fence=43,
            lifecycle_state="COMPLETION_CANDIDATE",
            worker_status="completed",
            required_action="REQUEST_HANDBACK",
        )
        handback = self.local_only_handback(
            predecessor,
            handback_id="completion-candidate-fence-43",
            now=iso(minutes=31),
        )
        refill = write_json(
            self.root / "completion-candidate-fence-43-refill.json",
            refill_request(
                request_id="completion-candidate-fence-43",
                now=iso(minutes=31),
            ),
        )

        closed = self.run_script(
            REFILL,
            "close-and-refill",
            "--predecessor-ticket",
            str(predecessor),
            "--handback-request",
            str(handback),
            "--refill-request",
            str(refill),
        )
        self.assertEqual(0, closed.returncode, closed.stderr)
        self.assertEqual("EMPTY", json.loads(closed.stdout)["result"]["outcome"])

    def test_expired_hold_mismatch_and_ordinary_expiry_remain_stale(self):
        predecessor = self.start_predecessor()
        handback = self.local_only_handback(
            predecessor,
            handback_id="stream-recorder-mismatch",
            now=iso(minutes=31),
        )
        refill = write_json(
            self.root / "stream-recorder-mismatch-refill.json",
            refill_request(
                request_id="stream-recorder-mismatch",
                now=iso(minutes=31),
            ),
        )

        ordinary = self.run_script(
            REFILL,
            "close-and-refill",
            "--predecessor-ticket",
            str(predecessor),
            "--handback-request",
            str(handback),
            "--refill-request",
            str(refill),
        )
        self.assertEqual(2, ordinary.returncode)
        self.assertEqual("RECEIPT_STALE", json.loads(ordinary.stderr)["error"]["code"])

        for label, replay_target, hold_fence in (
            ("target", "completed_local_artifact", 38),
            ("fence", "completed_local_only", 39),
        ):
            with self.subTest(label=label):
                self.set_control_schema_hold(
                    predecessor,
                    fence=38,
                    replay_target=replay_target,
                    hold_fence=hold_fence,
                )
                handback = self.local_only_handback(
                    predecessor,
                    handback_id="stream-recorder-mismatch",
                    now=iso(minutes=31),
                )
                rejected = self.run_script(
                    REFILL,
                    "close-and-refill",
                    "--predecessor-ticket",
                    str(predecessor),
                    "--handback-request",
                    str(handback),
                    "--refill-request",
                    str(refill),
                )
                self.assertEqual(2, rejected.returncode)
                self.assertEqual(
                    "RECEIPT_STALE",
                    json.loads(rejected.stderr)["error"]["code"],
                )
                state = json.loads(
                    (self.state / "fake-state.json").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    "RUNNING",
                    state["tasks"]["task-predecessor"]["state"],
                )
                self.assertFalse(
                    any(row["kind"] == "ARCHIVE_THREAD" for row in state["outbox"].values())
                )

    def test_close_and_refill_still_requires_a_committed_receipt(self):
        predecessor = self.start_predecessor("-missing-receipt")
        ticket = json.loads(predecessor.read_text(encoding="utf-8"))
        ticket["receipt"] = None
        predecessor.write_text(
            json.dumps(ticket, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        handback = write_json(
            self.root / "missing-receipt-handback.json",
            handback_request(
                task_id="task-predecessor-missing-receipt",
                handback_id="missing-receipt",
                now=iso(minutes=2),
            ),
        )
        refill = write_json(
            self.root / "missing-receipt-refill.json",
            refill_request(request_id="missing-receipt"),
        )

        rejected = self.run_script(
            REFILL,
            "close-and-refill",
            "--predecessor-ticket",
            str(predecessor),
            "--handback-request",
            str(handback),
            "--refill-request",
            str(refill),
        )
        self.assertEqual(2, rejected.returncode)
        self.assertEqual(
            "RECEIPT_MISSING",
            json.loads(rejected.stderr)["error"]["code"],
        )

    def test_expired_terminal_evidence_identity_and_lifecycle_mismatches_stay_stale(self):
        predecessor = self.start_predecessor("-terminal-mismatch")
        self.set_terminal_evidence(
            predecessor,
            fence=41,
            worker_status="completed",
        )
        state_path = self.state / "fake-state.json"
        baseline = json.loads(state_path.read_text(encoding="utf-8"))
        refill = write_json(
            self.root / "terminal-mismatch-refill.json",
            refill_request(
                request_id="terminal-mismatch",
                now=iso(minutes=31),
            ),
        )

        for label in (
            "task",
            "policy",
            "lease",
            "fence",
            "thread",
            "claim",
            "missing-signals",
            "wrong-action",
            "running",
            "nonlocal-disposition",
        ):
            with self.subTest(label=label):
                state = json.loads(json.dumps(baseline))
                task = state["tasks"]["task-predecessor-terminal-mismatch"]
                if label == "task":
                    task["task_id"] = "different-task"
                elif label == "policy":
                    task["policy_snapshot_revision"] += 1
                elif label == "lease":
                    task["lease_expires_at"] = iso(minutes=29)
                elif label == "fence":
                    task["claim_fencing_token"] += 1
                elif label == "thread":
                    task["receipt_external_thread_id"] = "different-thread"
                elif label == "claim":
                    task["owner_claim_id"] = "different-claim"
                elif label == "missing-signals":
                    task["lifecycle"]["completion_signals"] = []
                elif label == "wrong-action":
                    task["lifecycle"]["required_action"] = "CONTINUE"
                elif label == "running":
                    task["lifecycle"]["lifecycle_state"] = "RUNNING"
                state_path.write_text(
                    json.dumps(state, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                handback = self.local_only_handback(
                    predecessor,
                    handback_id=f"terminal-mismatch-{label}",
                    now=iso(minutes=31),
                )
                if label == "nonlocal-disposition":
                    value = json.loads(handback.read_text(encoding="utf-8"))
                    value["disposition"] = "completed"
                    handback.write_text(
                        json.dumps(value, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                rejected = self.run_script(
                    REFILL,
                    "close-and-refill",
                    "--predecessor-ticket",
                    str(predecessor),
                    "--handback-request",
                    str(handback),
                    "--refill-request",
                    str(refill),
                )
                self.assertEqual(2, rejected.returncode)
                self.assertEqual(
                    "RECEIPT_STALE",
                    json.loads(rejected.stderr)["error"]["code"],
                )
                unchanged = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    "RUNNING",
                    unchanged["tasks"]["task-predecessor-terminal-mismatch"][
                        "state"
                    ],
                )
                self.assertFalse(
                    any(
                        row["kind"] == "ARCHIVE_THREAD"
                        for row in unchanged["outbox"].values()
                    )
                )

    def test_no_commit_retry_is_idempotent_and_releases_nothing_early(self):
        predecessor = self.start_predecessor()
        handback = write_json(
            self.root / "screenbench-fence-42-no-commit.json",
            handback_request(
                task_id="task-predecessor",
                handback_id="screenbench-fence-42-no-commit",
                now=iso(minutes=2),
            ),
        )
        refill = write_json(
            self.root / "screenbench-fence-42-no-commit-refill.json",
            refill_request(request_id="screenbench-fence-42-no-commit"),
        )
        command = (
            "close-and-refill",
            "--predecessor-ticket",
            str(predecessor),
            "--handback-request",
            str(handback),
            "--refill-request",
            str(refill),
        )
        before = json.loads((self.state / "fake-state.json").read_text(encoding="utf-8"))
        failed = self.run_script(REFILL, *command, mode="fail-before-handback-commit")
        self.assertEqual(2, failed.returncode)
        self.assertEqual(
            "SYNTHETIC_HANDBACK_NOT_COMMITTED",
            json.loads(failed.stderr)["error"]["code"],
        )
        after_failure = json.loads(
            (self.state / "fake-state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(before["recycle_revision"], after_failure["recycle_revision"])
        self.assertEqual(
            "RUNNING",
            after_failure["tasks"]["task-predecessor"]["state"],
        )
        self.assertEqual({}, after_failure["handbacks"])
        self.assertFalse(
            any(row["kind"] == "ARCHIVE_THREAD" for row in after_failure["outbox"].values())
        )
        self.assertFalse((self.state / "pm-proxy-refill-ledger.json").exists())

        closed = self.run_script(REFILL, *command)
        self.assertEqual(0, closed.returncode, closed.stderr)
        replayed = self.run_script(REFILL, *command)
        self.assertEqual(0, replayed.returncode, replayed.stderr)
        self.assertTrue(json.loads(replayed.stdout)["result"]["replayed"])
        state = json.loads((self.state / "fake-state.json").read_text(encoding="utf-8"))
        archives = [row for row in state["outbox"].values() if row["kind"] == "ARCHIVE_THREAD"]
        self.assertEqual(1, len(archives))

    def test_under_capacity_exact_replacement_is_not_still_runnable(self):
        predecessor = self.start_predecessor("-target")
        state_path = self.state / "fake-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        peer = json.loads(
            json.dumps(state["tasks"]["task-predecessor-target"])
        )
        peer.update(
            {
                "task_id": "task-peer",
                "source_event_key": "peer-source",
                "outcome_key": "peer-outcome",
                "idempotency_key": "peer-idem",
                "fencing_token": 2,
            }
        )
        peer["target"]["path"] = "/peer"
        state["tasks"]["task-peer"] = peer
        state_path.write_text(json.dumps(state), encoding="utf-8")
        successor = launch_request(
            task_id="task-under-cap-successor",
            source_event_key="under-cap-successor-source",
            outcome_key="under-cap-successor-outcome",
            idempotency_key="under-cap-successor-idem",
            prompt="SYNTHETIC_UNDER_CAP_SUCCESSOR",
            now=iso(minutes=2),
            lease_expires_at=iso(minutes=32),
        )
        handback = write_json(
            self.root / "under-cap-handback.json",
            handback_request(
                task_id="task-predecessor-target",
                handback_id="under-cap-close",
                now=iso(minutes=2),
            ),
        )
        refill = write_json(
            self.root / "under-cap-refill.json",
            refill_request(
                candidates=[successor],
                request_id="under-cap-refill",
                capacity=4,
            ),
        )
        closed = self.run_script(
            REFILL,
            "close-and-refill",
            "--predecessor-ticket",
            str(predecessor),
            "--handback-request",
            str(handback),
            "--refill-request",
            str(refill),
        )
        self.assertEqual(0, closed.returncode, closed.stderr)
        result = json.loads(closed.stdout)["result"]
        self.assertEqual("SUCCESSOR_RESERVED", result["outcome"])
        self.assertEqual(2, result["slot_truth"]["active_or_reserved_count"])
        self.assertEqual(2, result["slot_truth"]["deficit"])
        self.assertEqual([], result["slot_truth"]["runnable_task_ids"])
        self.assertEqual(0, result["slot_truth"]["runnable_queue_count"])
        self.assertIsNone(result["slot_truth"]["failure_state"])

    def test_invalid_interrupted_observation_and_capacity_deficit_fail_visibly(self):
        refill_value = refill_request(
            candidates=[launch_request(task_id="runnable")],
            status="interrupted/notLoaded",
            valid_clean_handback=False,
        )
        refill = write_json(self.root / "invalid-refill.json", refill_value)
        status = self.run_script(REFILL, "slot-status", "--refill-request", str(refill))
        self.assertEqual(status.returncode, 2)
        self.assertEqual(json.loads(status.stderr)["error"]["code"], "TERMINAL_EVIDENCE_INVALID")

        valid = write_json(
            self.root / "deficit.json",
            refill_request(candidates=[launch_request(task_id="runnable")]),
        )
        deficit = self.run_script(REFILL, "slot-status", "--refill-request", str(valid))
        self.assertEqual(deficit.returncode, 0, deficit.stderr)
        truth = json.loads(deficit.stdout)["result"]
        self.assertEqual(truth["failure_state"], "CAPACITY_DEFICIT")
        self.assertEqual(truth["active_or_reserved_count"], 0)
        self.assertEqual(truth["runnable_queue_count"], 1)

        watchdog = self.run_script(
            REFILL,
            "watchdog-refill",
            "--refill-request",
            str(valid),
        )
        self.assertEqual(watchdog.returncode, 0, watchdog.stderr)
        watchdog_result = json.loads(watchdog.stdout)["result"]
        self.assertEqual(watchdog_result["outcome"], "SUCCESSOR_RESERVED")
        self.assertEqual(len(watchdog_result["launches"]), 1)
        self.assertIsNone(watchdog_result["slot_truth"]["failure_state"])

    def test_100_concurrent_close_refill_attempts_create_one_successor(self):
        root = private_temp("pm-proxy-close-race-")
        cli = make_fake_install(root)
        state = root / "state"
        state.mkdir(mode=0o700)

        def invoke(script: Path, *args: str):
            return [
                sys.executable,
                str(script),
                "--cli",
                str(cli),
                "--state-dir",
                str(state),
                *args,
            ]

        predecessor_recycle = write_json(root / "pre-recycle.json", recycle_request())
        predecessor_launch = write_json(root / "pre-launch.json", launch_request())
        runtime_attestation = write_json(
            root / "runtime-attestation.json",
            config_verified_runtime_attestation(),
        )
        predecessor_ticket = state / "predecessor.ticket.json"
        self.assertEqual(
            0,
            subprocess.run(
                invoke(
                    BRIDGE,
                    "prepare-launch",
                    "--recycle-request",
                    str(predecessor_recycle),
                    "--launch-request",
                    str(predecessor_launch),
                    "--ticket",
                    str(predecessor_ticket),
                ),
                capture_output=True,
                check=False,
            ).returncode,
        )
        self.assertEqual(
            0,
            subprocess.run(
                invoke(
                    BRIDGE,
                    "record-launch-receipt",
                    "--ticket",
                    str(predecessor_ticket),
                    "--external-thread-id",
                    "thread-predecessor",
                    "--runtime-attestation",
                    str(runtime_attestation),
                    "--request-id",
                    "pre-receipt",
                    "--now",
                    iso(minutes=1),
                ),
                capture_output=True,
                check=False,
            ).returncode,
        )
        successor = launch_request(
            task_id="successor",
            source_event_key="next-source",
            outcome_key="next-outcome",
            idempotency_key="next-idem",
            now=iso(minutes=2),
            lease_expires_at=iso(minutes=32),
        )
        handback = write_json(
            root / "handback.json",
            handback_request(
                handback_id="close-race",
                now=iso(minutes=2),
            ),
        )
        refill = write_json(
            root / "refill.json",
            refill_request(
                candidates=[successor],
                request_id="close-race",
                status="interrupted/notLoaded",
            ),
        )
        command = invoke(
            REFILL,
            "close-and-refill",
            "--predecessor-ticket",
            str(predecessor_ticket),
            "--handback-request",
            str(handback),
            "--refill-request",
            str(refill),
        )
        processes = [
            subprocess.Popen(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for _ in range(100)
        ]
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            results.append((process.returncode, stdout, stderr))
        self.assertEqual({item[0] for item in results}, {0})
        payloads = [json.loads(item[1])["result"] for item in results]
        self.assertEqual(sum(not bool(item.get("replayed")) for item in payloads), 1)
        state_value = json.loads((state / "fake-state.json").read_text(encoding="utf-8"))
        self.assertEqual(set(state_value["tasks"]), {"task-1", "successor"})
        successor_creates = [
            row
            for row in state_value["outbox"].values()
            if row["kind"] == "CREATE_THREAD" and row["task_id"] == "successor"
        ]
        self.assertEqual(len(successor_creates), 1)


if __name__ == "__main__":
    unittest.main()
