"""Contract coverage for the stack-agnostic orchestrator-session add-on."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "firestarter.config.json"
GENERATOR = ROOT / "bin" / "generate.py"
ADDON = ROOT / "addons" / "orchestrator_session" / "common"
CANONICAL_BILL = ADDON / "ORCHESTRATOR_BILL_OF_RIGHTS.md"
REQUIRED_FILES = {
    "AGENTS.orchestrator.md",
    "ORCHESTRATOR_BILL_OF_RIGHTS.md",
    "ORCHESTRATOR_PROMPT.md",
    "decisions-board/decisions.html",
    "decisions-board/decisions.json",
    "docs/ORCHESTRATOR_SESSION.md",
    "orchestrator-control/README.md",
    "orchestrator-control/VERSION",
    "orchestrator-control/dashboard.html",
    "orchestrator-control/docs/PHASE2_PLUGIN_INTEGRATION.md",
    "orchestrator-control/orchestrator_control.py",
    "orchestrator-control/policy-ledger.json",
    "orchestrator-control/schemas/classify-decision.request.schema.json",
    "orchestrator-control/schemas/classify-decision.response.schema.json",
    "orchestrator-control/schemas/effective-rules.request.schema.json",
    "orchestrator-control/schemas/heartbeat.request.schema.json",
    "orchestrator-control/schemas/machine-response.schema.json",
    "orchestrator-control/schemas/migrate-decisions.request.schema.json",
    "orchestrator-control/schemas/policy-ledger.schema.json",
    "orchestrator-control/schemas/prepare-launch.request.schema.json",
    "orchestrator-control/schemas/prepare-launch.response.schema.json",
    "orchestrator-control/schemas/receipt.request.schema.json",
    "orchestrator-control/schemas/record-handback.request.schema.json",
    "orchestrator-control/schemas/record-handback.response.schema.json",
    "orchestrator-control/schemas/record-policy-rule.request.schema.json",
    "orchestrator-control/schemas/recycle-queue.request.schema.json",
    "orchestrator-control/schemas/recycle-queue.response.schema.json",
    "orchestrator-control/schemas/shared.schema.json",
    "orchestrator-control/schemas/takeover-lease.request.schema.json",
}
REQUIRED_FAILURE_PREVENTION_CLAUSES = {
    "blocked_queue": "Blocked work is a reviewable queue, not permanent parking.",
    "blocked_queue_priority": (
        "resume the highest-value safely unblocked task first."
    ),
    "canonical_owner": "Each repository and mutable path has one canonical owner.",
    "closure_transaction": (
        "Task closure and successor or replacement creation are one lifecycle "
        "transaction."
    ),
    "duplicate_stop": (
        "the duplicate lane stops at read-only\n"
        "  reconciliation, returns any unique evidence, performs no write, and archives."
    ),
    "fidelity": "Orchestration fidelity outranks opportunistic local execution.",
    "launch_envelope": (
        "Every task launch envelope includes all applicable standing decisions,"
    ),
    "ledger_before_prompt": (
        "Consult the PM-proxy decision ledger before any approval prompt."
    ),
    "prompt_boundary": "Prompts are reserved for genuine owner gates.",
    "resource_return": (
        "every completed lane releases its task-owned resources and returns its\n"
        "evidence to the orchestrator."
    ),
    "transactional_reservation": (
        "Reserve the task, all ownership claims, and\n"
        "  its create outbox in one transaction before external task creation"
    ),
    "fencing": (
        "monotonically increasing fence so the prior worker cannot heartbeat, mutate,"
    ),
    "privacy_safe_policy": (
        "Never\n"
        "persist a raw conversation, prompt, secret, private value, stdout, diff, or"
    ),
}


class OrchestratorSessionContractTests(unittest.TestCase):
    def test_every_declared_stack_stamps_the_exact_canonical_bill(self) -> None:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        stacks = config["stack"]
        self.assertIsInstance(stacks, list)
        self.assertGreater(len(stacks), 0)

        canonical_bytes = CANONICAL_BILL.read_bytes()
        canonical_text = canonical_bytes.decode("utf-8")
        canonical_files = {
            path.relative_to(ADDON).as_posix(): path.read_bytes()
            for path in ADDON.rglob("*")
            if path.is_file()
        }
        self.assertTrue(REQUIRED_FILES <= canonical_files.keys())
        for clause, required_text in REQUIRED_FAILURE_PREVENTION_CLAUSES.items():
            with self.subTest(clause=clause):
                self.assertIn(required_text, canonical_text)

        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            for stack in stacks:
                with self.subTest(stack=stack):
                    output = output_root / stack
                    subprocess.run(
                        [
                            sys.executable,
                            str(GENERATOR),
                            "--defaults",
                            "--set",
                            f"stack={stack}",
                            "--set",
                            "include_orchestrator_session=yes",
                            "--output",
                            str(output),
                        ],
                        cwd=ROOT,
                        check=True,
                        capture_output=True,
                        text=True,
                    )

                    stamped = {
                        path.relative_to(output).as_posix()
                        for path in output.rglob("*")
                        if path.is_file()
                    }
                    self.assertTrue(
                        REQUIRED_FILES <= stamped,
                        f"{stack} missing {sorted(REQUIRED_FILES - stamped)}",
                    )
                    self.assertEqual(
                        canonical_bytes,
                        (output / "ORCHESTRATOR_BILL_OF_RIGHTS.md").read_bytes(),
                        f"{stack} changed the canonical Bill while stamping",
                    )
                    for relative, expected_bytes in canonical_files.items():
                        with self.subTest(stack=stack, file=relative):
                            self.assertEqual(
                                expected_bytes,
                                (output / relative).read_bytes(),
                                f"{stack} changed {relative} while stamping",
                            )

                    prompt = (output / "ORCHESTRATOR_PROMPT.md").read_text(
                        encoding="utf-8"
                    )
                    agents = (output / "AGENTS.orchestrator.md").read_text(
                        encoding="utf-8"
                    )
                    self.assertIn(
                        "ORCHESTRATOR_BILL_OF_RIGHTS.md",
                        prompt,
                    )
                    self.assertIn(
                        "ORCHESTRATOR_BILL_OF_RIGHTS.md",
                        agents,
                    )
                    self.assertLess(len(prompt), 1_000)
                    self.assertLess(len(agents), 1_500)

                    state = output_root / f"{stack}-control-state"
                    control = output / "orchestrator-control" / "orchestrator_control.py"
                    initialized = subprocess.run(
                        [
                            sys.executable,
                            "-B",
                            str(control),
                            "--state-dir",
                            str(state),
                            "init",
                            "--now",
                            "2026-07-28T18:00:00Z",
                        ],
                        cwd=output,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    self.assertTrue(json.loads(initialized.stdout)["ok"])
                    status = subprocess.run(
                        [
                            sys.executable,
                            "-B",
                            str(control),
                            "--state-dir",
                            str(state),
                            "status",
                        ],
                        cwd=output,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual("1.0", json.loads(status.stdout)["result"]["schema_version"])


if __name__ == "__main__":
    unittest.main()
