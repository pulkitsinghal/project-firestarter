"""Adversarial contract for honest producer->consumer receipts: queued is not accepted.

`scripts/work-receipt.sh` is the generic reference. These tests prove the two
invariants the issue names -- an unavailable consumer does not mark work
requested, and the later retry succeeds -- plus the full receipt taxonomy, the
`check` verifier that fails a claim overstating reality, and fail-closed usage.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "template" / "scripts" / "work-receipt.sh"
BASH = os.environ.get("WORK_RECEIPT_BASH", "bash")


class WorkReceiptContract(unittest.TestCase):
    def run_tool(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, str(SCRIPT), *args],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=15,
        )

    def classify(self, item: str, consumer: str, handoff: str, progress: str) -> dict:
        result = self.run_tool(
            "classify",
            "--item", item,
            "--consumer", consumer,
            "--handoff", handoff,
            "--progress", progress,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    # --- the two headline invariants from the issue -----------------------------

    def test_unavailable_consumer_is_blocked_and_does_not_mark_requested(self) -> None:
        # queued is NOT accepted: no worker and no durable handoff -> blocked, the
        # idempotency/"requested" marker is not consumed, and the item stays retryable.
        receipt = self.classify("yes", "absent", "none", "none")
        self.assertEqual(receipt["receipt"], "blocked")
        self.assertIs(receipt["requested"], False)
        self.assertIs(receipt["retryable"], True)

    def test_later_retry_with_a_real_consumer_is_accepted(self) -> None:
        # The same item, retried once a worker is present, is accepted (queued),
        # and only now is the request marked.
        receipt = self.classify("yes", "present", "none", "none")
        self.assertEqual(receipt["receipt"], "queued")
        self.assertIs(receipt["requested"], True)
        self.assertIs(receipt["retryable"], True)

    def test_durable_handoff_counts_as_acceptance_without_a_live_consumer(self) -> None:
        receipt = self.classify("yes", "absent", "durable", "none")
        self.assertEqual(receipt["receipt"], "queued")
        self.assertIs(receipt["requested"], True)

    # --- the distinct receipts the UI must not blur -----------------------------

    def test_every_receipt_state_is_distinct(self) -> None:
        cases = {
            ("no", "present", "none", "none"): ("no-op", False, False),
            ("yes", "absent", "none", "none"): ("blocked", False, True),
            ("yes", "present", "none", "none"): ("queued", True, True),
            ("yes", "present", "none", "some"): ("partial", True, True),
            ("yes", "present", "none", "all"): ("completed", True, False),
        }
        for (item, consumer, handoff, progress), (receipt, req, ret) in cases.items():
            with self.subTest(item=item, consumer=consumer, progress=progress):
                out = self.classify(item, consumer, handoff, progress)
                self.assertEqual(out["receipt"], receipt)
                self.assertIs(out["requested"], req)
                self.assertIs(out["retryable"], ret)

    def test_no_item_is_noop_regardless_of_consumer(self) -> None:
        for consumer in ("present", "absent"):
            with self.subTest(consumer=consumer):
                out = self.classify("no", consumer, "none", "none")
                self.assertEqual(out["receipt"], "no-op")
                self.assertIs(out["requested"], False)

    # --- check: a claim that overstates reality is caught -----------------------

    def test_check_rejects_a_queued_claim_with_no_consumer(self) -> None:
        result = self.run_tool(
            "check", "--claim", "queued",
            "--item", "yes", "--consumer", "absent",
            "--handoff", "none", "--progress", "none",
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("DISHONEST", result.stderr)
        self.assertIn("honest=blocked", result.stderr)

    def test_check_accepts_an_honest_blocked_claim(self) -> None:
        result = self.run_tool(
            "check", "--claim", "blocked",
            "--item", "yes", "--consumer", "absent",
            "--handoff", "none", "--progress", "none",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK receipt=blocked", result.stdout)

    def test_check_rejects_blocked_that_consumed_the_requested_marker(self) -> None:
        # A blocked receipt must not consume the idempotency / requested marker.
        result = self.run_tool(
            "check", "--claim", "blocked",
            "--item", "yes", "--consumer", "absent",
            "--handoff", "none", "--progress", "none",
            "--requested", "true",
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("mismatch=requested", result.stderr)

    def test_check_rejects_completed_claim_when_work_is_only_partial(self) -> None:
        result = self.run_tool(
            "check", "--claim", "completed",
            "--item", "yes", "--consumer", "present",
            "--handoff", "none", "--progress", "some",
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("honest=partial", result.stderr)

    def test_check_accepts_matching_flag_claims(self) -> None:
        result = self.run_tool(
            "check", "--claim", "queued",
            "--item", "yes", "--consumer", "present",
            "--handoff", "none", "--progress", "none",
            "--requested", "true", "--retryable", "true",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    # --- usage / fail-closed: no permissive default for a load-bearing flag -----

    def test_invalid_and_missing_input_is_usage_error(self) -> None:
        cases = [
            [],  # no subcommand
            ["classify"],  # no flags
            ["bogus", "--item", "yes"],  # unknown subcommand
            ["classify", "--item", "maybe", "--consumer", "present",
             "--handoff", "none", "--progress", "none"],  # bad enum value
            ["classify", "--item", "yes", "--consumer", "present",
             "--handoff", "none"],  # missing --progress (no permissive default)
            ["classify", "--item", "yes", "--consumer", "present",
             "--handoff", "none", "--progress", "none", "--bogus", "x"],  # unknown flag
            ["classify", "--item"],  # missing value for a flag
            ["check", "--item", "yes", "--consumer", "present",
             "--handoff", "none", "--progress", "none"],  # check without --claim
        ]
        for args in cases:
            with self.subTest(args=args):
                result = self.run_tool(*args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_classify_output_is_only_enum_state(self) -> None:
        # The tool takes only enum tokens; classify emits exactly the receipt JSON
        # on stdout and nothing on stderr, so there is no channel for caller data.
        result = self.run_tool(
            "classify", "--item", "yes", "--consumer", "absent",
            "--handoff", "none", "--progress", "none",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {"receipt": "blocked", "requested": False, "retryable": True},
        )
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
