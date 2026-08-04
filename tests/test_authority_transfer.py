"""Fail-closed single-leader federation and authority-transfer contracts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL_ROOT = (
    ROOT / "addons" / "orchestrator_session" / "common" / "orchestrator-control"
)
CLI = CONTROL_ROOT / "orchestrator_control.py"
LEDGER = CONTROL_ROOT / "policy-ledger.json"
NOW = "2026-08-03T18:00:00Z"


class AuthorityTransferTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = tempfile.TemporaryDirectory(prefix="orc-authority-transfer-")
        self.root = Path(self.sandbox.name)
        self.source_a = self.root / "source-a"
        self.source_b = self.root / "source-b"
        self.target = self.root / "target"
        for state in (self.source_a, self.source_b, self.target):
            self.run_cli(state, "init", now=NOW)

    def tearDown(self) -> None:
        self.sandbox.cleanup()

    def run_cli(
        self,
        state: Path,
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
            str(state),
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

    def status(self, state: Path) -> dict[str, object]:
        return self.run_cli(state, "status")["result"]

    @staticmethod
    def prepare_request(
        *, transfer_id: str, target_id: str, revision: int, suffix: str
    ) -> dict[str, object]:
        return {
            "interface_version": "1.0",
            "request_id": f"prepare-{suffix}",
            "transfer_id": transfer_id,
            "target_authority_id": target_id,
            "expected_state_revision": revision,
            "evidence_refs": ["owner-authorized-federation"],
            "now": NOW,
        }

    @staticmethod
    def capacity_request(status: dict[str, object], suffix: str) -> dict[str, object]:
        capacity = status["worker_capacity"]["configured_capacity"]
        return {
            "interface_version": "1.0",
            "request_id": f"capacity-{suffix}",
            "expected_state_revision": status["revision"],
            "expected_configured_capacity": capacity,
            "requested_configured_capacity": capacity + 1,
            "evidence_refs": ["synthetic-authority-gate"],
            "now": NOW,
        }

    def prepare_sources(self, transfer_id: str) -> tuple[dict[str, object], dict[str, object]]:
        target_status = self.status(self.target)
        target_id = target_status["authority"]["authority_id"]
        receipts = []
        for suffix, state in (("a", self.source_a), ("b", self.source_b)):
            source_status = self.status(state)
            prepared = self.run_cli(
                state,
                "prepare-authority-transfer",
                self.prepare_request(
                    transfer_id=transfer_id,
                    target_id=target_id,
                    revision=source_status["revision"],
                    suffix=suffix,
                ),
            )["result"]
            receipts.append(prepared)
        return receipts[0], receipts[1]

    def stage_target(
        self, transfer_id: str, source_receipts: list[dict[str, object]]
    ) -> dict[str, object]:
        return self.run_cli(
            self.target,
            "stage-federation",
            {
                "interface_version": "1.0",
                "request_id": "stage-target",
                "transfer_id": transfer_id,
                "expected_state_revision": self.status(self.target)["revision"],
                "source_receipts": source_receipts,
                "evidence_refs": ["two-source-receipts-verified"],
                "now": NOW,
            },
        )["result"]

    def test_two_sources_become_subordinates_of_one_active_root(self) -> None:
        transfer_id = "federation-two-to-one"
        source_a, source_b = self.prepare_sources(transfer_id)
        for state in (self.source_a, self.source_b):
            frozen_status = self.status(state)
            self.assertEqual("SOURCE_PREPARED", frozen_status["authority"]["state"])
            denied = self.run_cli(
                state,
                "configure-capacity",
                self.capacity_request(frozen_status, state.name),
                expected=3,
            )
            self.assertEqual("AUTHORITY_TRANSFER_FROZEN", denied["error"]["code"])

        stage = self.stage_target(transfer_id, [source_a, source_b])
        finalized = []
        for suffix, state in (("a", self.source_a), ("b", self.source_b)):
            result = self.run_cli(
                state,
                "finalize-authority-transfer",
                {
                    "interface_version": "1.0",
                    "request_id": f"finalize-{suffix}",
                    "transfer_id": transfer_id,
                    "target_stage_receipt": stage,
                    "now": NOW,
                },
            )["result"]
            finalized.append(result)
            self.assertEqual("SOURCE_FINALIZED", result["phase"])
            self.assertEqual("SUBORDINATE_PENDING", self.status(state)["authority"]["state"])

        activation_request = {
            "interface_version": "1.0",
            "request_id": "activate-target",
            "transfer_id": transfer_id,
            "source_finalize_receipts": finalized,
            "evidence_refs": ["all-old-roots-demoted"],
            "now": NOW,
        }
        activated = self.run_cli(
            self.target, "activate-federation", activation_request
        )["result"]
        replay = self.run_cli(
            self.target, "activate-federation", activation_request
        )["result"]
        self.assertTrue(replay["replayed"])
        self.assertEqual(activated["receipt_sha256"], replay["receipt_sha256"])

        for suffix, state in (("a", self.source_a), ("b", self.source_b)):
            enabled = self.run_cli(
                state,
                "enable-subordinate",
                {
                    "interface_version": "1.0",
                    "request_id": f"enable-{suffix}",
                    "transfer_id": transfer_id,
                    "target_activation_receipt": activated,
                    "now": NOW,
                },
            )["result"]
            self.assertEqual("SUBORDINATE_ACTIVE", enabled["phase"])

        target = self.status(self.target)
        self.assertEqual("ACTIVE_FEDERATION_ROOT", target["authority"]["state"])
        self.assertEqual(8, target["authority"]["federated_configured_capacity"])
        self.assertFalse(target["authority"]["local_worker_launch_allowed"])
        self.assertTrue(target["authority"]["requires_subordinate_shard"])
        self.assertEqual(2, len(target["authority"]["federation_members"]))
        denied = self.run_cli(
            self.target,
            "configure-capacity",
            self.capacity_request(target, "target"),
            expected=3,
        )
        self.assertEqual("FEDERATION_SHARD_REQUIRED", denied["error"]["code"])

        target_id = target["authority"]["authority_id"]
        for state in (self.source_a, self.source_b):
            subordinate = self.status(state)
            self.assertEqual("SUBORDINATE", subordinate["authority"]["state"])
            self.assertEqual("SUBORDINATE", subordinate["authority"]["role"])
            self.assertEqual(target_id, subordinate["authority"]["parent_authority_id"])
            self.assertTrue(subordinate["authority"]["local_worker_launch_allowed"])

    def test_tampered_receipt_and_post_demotion_abort_fail_closed(self) -> None:
        transfer_id = "federation-tamper"
        source_a, source_b = self.prepare_sources(transfer_id)
        tampered = dict(source_a)
        tampered["configured_capacity"] = 64
        denied = self.run_cli(
            self.target,
            "stage-federation",
            {
                "interface_version": "1.0",
                "request_id": "stage-tampered",
                "transfer_id": transfer_id,
                "expected_state_revision": self.status(self.target)["revision"],
                "source_receipts": [tampered, source_b],
                "evidence_refs": ["tampered-receipt-fixture"],
                "now": NOW,
            },
            expected=2,
        )
        self.assertEqual("AUTHORITY_RECEIPT_INVALID", denied["error"]["code"])

        stage = self.stage_target(transfer_id, [source_a, source_b])
        self.run_cli(
            self.source_a,
            "finalize-authority-transfer",
            {
                "interface_version": "1.0",
                "request_id": "finalize-a",
                "transfer_id": transfer_id,
                "target_stage_receipt": stage,
                "now": NOW,
            },
        )
        source_status = self.status(self.source_a)
        denied = self.run_cli(
            self.source_a,
            "abort-authority-transfer",
            {
                "interface_version": "1.0",
                "request_id": "abort-after-demotion",
                "transfer_id": transfer_id,
                "expected_authority_state": "SOURCE_PREPARED",
                "expected_state_revision": source_status["revision"],
                "target_activation_absent": True,
                "reason_code": "SYNTHETIC_ABORT",
                "evidence_refs": ["post-demotion-abort-fixture"],
                "now": NOW,
            },
            expected=3,
        )
        self.assertEqual("AUTHORITY_STATE_CONFLICT", denied["error"]["code"])

    def test_uncommitted_stage_can_abort_target_then_sources(self) -> None:
        transfer_id = "federation-abort"
        source_a, source_b = self.prepare_sources(transfer_id)
        self.stage_target(transfer_id, [source_a, source_b])
        for suffix, state in (
            ("target", self.target),
            ("a", self.source_a),
            ("b", self.source_b),
        ):
            status = self.status(state)
            aborted = self.run_cli(
                state,
                "abort-authority-transfer",
                {
                    "interface_version": "1.0",
                    "request_id": f"abort-{suffix}",
                    "transfer_id": transfer_id,
                    "expected_authority_state": status["authority"]["state"],
                    "expected_state_revision": status["revision"],
                    "target_activation_absent": True,
                    "reason_code": "SYNTHETIC_ROLLBACK",
                    "evidence_refs": ["owner-verified-no-activation"],
                    "now": NOW,
                },
            )["result"]
            self.assertEqual("ABORTED", aborted["phase"])
            self.assertEqual("ACTIVE_ROOT", self.status(state)["authority"]["state"])


if __name__ == "__main__":
    unittest.main()
