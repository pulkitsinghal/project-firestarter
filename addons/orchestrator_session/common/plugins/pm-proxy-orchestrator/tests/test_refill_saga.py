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

    def run_script(self, script: Path, *args: str):
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
