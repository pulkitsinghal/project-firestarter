"""Deterministic regressions for the mandatory root-orchestrator role guard."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = (
    ROOT
    / "addons"
    / "orchestrator_session"
    / "common"
    / "orchestrator-control"
    / "root_role_guard.py"
)
CONTROL_CLI = MODULE.with_name("orchestrator_control.py")
POLICY_LEDGER = MODULE.with_name("policy-ledger.json")
NOW = "2026-07-28T18:00:00Z"

SPEC = importlib.util.spec_from_file_location("root_role_guard", MODULE)
assert SPEC and SPEC.loader
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def request(action_type: str, **updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "interface_version": "1.0",
        "request_id": f"request-{action_type}",
        "action_id": f"action-{action_type}",
        "action_type": action_type,
        "delegable_worker_available": True,
        "scope_id": "portfolio",
        "now": NOW,
    }
    value.update(updates)
    return value


def launch_receipt() -> dict[str, object]:
    return {
        "kind": "launch_receipt",
        "verified": True,
        "task_id": "task-1",
        "receipt_id": "receipt-1",
        "external_thread_id": "thread-1",
        "fencing_token": "fence-1",
        "lease_epoch": 1,
        "policy_snapshot_revision": "revision-1",
    }


def execution_exception(
    action_type: str,
    *,
    action_id: str | None = None,
    scope_id: str = "portfolio",
    issued_at: str = "2026-07-28T17:59:00Z",
    expires_at: str = "2026-07-28T18:04:00Z",
) -> dict[str, object]:
    return {
        "receipt_type": "ROOT_EXECUTION_EXCEPTION",
        "receipt_id": f"exception-{action_type}",
        "action_id": action_id or f"action-{action_type}",
        "action_type": action_type,
        "scope_id": scope_id,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "nondelegable_recovery": True,
        "eligible_worker_count": 0,
        "authority": "SYSTEM_NONDELEGABLE_RECOVERY",
    }


class RootRoleGuardTests(unittest.TestCase):
    def evaluate(self, action_type: str, **updates: object) -> dict[str, object]:
        return guard.classify_action(request(action_type, **updates))["result"]

    def test_root_cannot_invent_duration_estimate_or_design_after_delegation(self) -> None:
        for action in ("estimate_duration", "design_solution"):
            with self.subTest(action=action):
                result = self.evaluate(action)
                self.assertEqual("TASK_EXECUTION", result["classification"])
                self.assertEqual("DENY", result["decision"])
                self.assertEqual(
                    "PREPARE_SUCCESSOR_HANDOFF", result["required_action"]
                )

    def test_root_repository_inspection_is_worker_execution(self) -> None:
        result = self.evaluate("inspect_repository")
        self.assertEqual("ROOT_TASK_EXECUTION_FORBIDDEN", result["reason_code"])
        self.assertEqual("DENY", result["decision"])

    def test_send_message_does_not_prove_implemented_or_complete(self) -> None:
        for status in ("implemented", "complete", "tested"):
            with self.subTest(status=status):
                result = self.evaluate(
                    "synthesize_worker_evidence",
                    target_status=status,
                    evidence=[{"kind": "send_message", "verified": True}],
                )
                self.assertEqual("DENY", result["decision"])
                self.assertEqual("UNTRUTHFUL_STATUS_FORBIDDEN", result["reason_code"])
                self.assertEqual(
                    "PROVIDE_WORKER_EVIDENCE", result["required_action"]
                )

    def test_capacity_fill_without_exact_receipt_is_denied(self) -> None:
        absent = self.evaluate("refill_capacity")
        incomplete = self.evaluate(
            "refill_capacity",
            evidence=[{"kind": "launch_receipt", "verified": True}],
        )
        for result in (absent, incomplete):
            self.assertEqual("DENY", result["decision"])
            self.assertEqual("EXACT_LAUNCH_RECEIPT_REQUIRED", result["reason_code"])
            self.assertEqual("PROVIDE_EXACT_RECEIPT", result["required_action"])

    def test_capacity_fill_with_exact_verified_receipt_is_allowed(self) -> None:
        result = self.evaluate("refill_capacity", evidence=[launch_receipt()])
        self.assertEqual("ORCHESTRATION", result["classification"])
        self.assertEqual("ALLOW", result["decision"])

    def test_capacity_reconfiguration_is_typed_orchestration_not_task_execution(
        self,
    ) -> None:
        result = self.evaluate("configure_capacity")
        self.assertEqual("ORCHESTRATION", result["classification"])
        self.assertEqual("ALLOW", result["decision"])
        self.assertEqual("ROOT_ORCHESTRATION_ALLOWED", result["reason_code"])

    def test_truthful_statuses_require_matching_worker_evidence(self) -> None:
        cases = {
            "assigned": [launch_receipt()],
            "running": [
                launch_receipt(),
                {"kind": "heartbeat", "verified": True},
            ],
            "validated": [
                {
                    "kind": "worker_handback",
                    "verified": True,
                    "handback_id": "handback-1",
                },
                {"kind": "validation", "verified": True},
            ],
            "merged": [
                {
                    "kind": "worker_handback",
                    "verified": True,
                    "handback_id": "handback-1",
                },
                {"kind": "merge", "verified": True},
            ],
            "deployed": [
                {
                    "kind": "worker_handback",
                    "verified": True,
                    "handback_id": "handback-1",
                },
                {"kind": "deployment", "verified": True},
            ],
        }
        for status, evidence in cases.items():
            with self.subTest(status=status):
                denied = self.evaluate(
                    "synthesize_worker_evidence",
                    target_status=status,
                    evidence=evidence[:-1],
                )
                allowed = self.evaluate(
                    "synthesize_worker_evidence",
                    target_status=status,
                    evidence=evidence,
                )
                self.assertEqual("DENY", denied["decision"])
                self.assertEqual("ALLOW", allowed["decision"])
                self.assertEqual(status, allowed["truthful_status"])

    def test_unknown_action_fails_closed(self) -> None:
        result = self.evaluate("read_anything_convenient")
        self.assertEqual("UNKNOWN", result["classification"])
        self.assertEqual("DENY", result["decision"])

    def test_exact_short_lived_nondelegable_exception_is_narrowly_allowed(
        self,
    ) -> None:
        result = self.evaluate(
            "run_tests",
            delegable_worker_available=False,
            exception_receipt=execution_exception("run_tests"),
        )
        self.assertEqual("ALLOW", result["decision"])
        self.assertEqual("TASK_EXECUTION_EXCEPTION", result["classification"])
        self.assertTrue(result["exception_receipt_accepted"])
        self.assertTrue(result["dispatcher_enforcement_required"])
        self.assertFalse(result["runtime_enforcement_proven"])

    def test_delegable_stale_and_scope_mismatched_exceptions_are_denied(
        self,
    ) -> None:
        cases = (
            {
                "delegable_worker_available": True,
                "exception_receipt": execution_exception("run_tests"),
            },
            {
                "delegable_worker_available": False,
                "exception_receipt": execution_exception(
                    "run_tests",
                    issued_at="2026-07-28T17:00:00Z",
                    expires_at="2026-07-28T17:05:00Z",
                ),
            },
            {
                "delegable_worker_available": False,
                "exception_receipt": execution_exception(
                    "run_tests", scope_id="different-scope"
                ),
            },
        )
        for updates in cases:
            with self.subTest(updates=updates):
                result = self.evaluate("run_tests", **updates)
                self.assertEqual("DENY", result["decision"])
                self.assertFalse(result["exception_receipt_accepted"])

    def test_owner_notification_requires_verified_owner_gate(self) -> None:
        result = self.evaluate("notify_owner")
        self.assertEqual("DENY", result["decision"])
        self.assertEqual("VERIFIED_OWNER_GATE_REQUIRED", result["reason_code"])
        self.assertFalse(result["owner_notification_authorized"])

    def test_private_prompt_path_and_secret_fields_are_refused(self) -> None:
        for field in ("prompt", "private_content", "phi", "secret", "repo_path"):
            with self.subTest(field=field):
                value = request("receive_owner_intent")
                value[field] = "must-not-be-retained"
                with self.assertRaisesRegex(
                    guard.GuardInputError, "not accepted"
                ):
                    guard.classify_action(value)

    def test_audit_is_bounded_and_contains_only_redacted_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as sandbox:
            state = Path(sandbox) / "root-role-audit.json"
            private_identifiers = {
                "task_id": "task-private-1",
                "receipt_id": "receipt-private-1",
                "external_thread_id": "thread-private-1",
                "fencing_token": "fence-private-1",
                "lease_epoch": 1,
                "policy_snapshot_revision": "revision-private-1",
            }
            evidence = launch_receipt()
            evidence.update(private_identifiers)
            for index in range(guard.MAX_AUDIT_RECORDS + 5):
                value = request(
                    "refill_capacity",
                    evidence=[evidence],
                )
                value["request_id"] = f"request-{index}"
                value["action_id"] = f"action-{index}"
                guard.evaluate_action(value, state_file=state)

            payload = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(guard.MAX_AUDIT_RECORDS, len(payload["records"]))
            serialized = state.read_text(encoding="utf-8")
            for key, private_value in private_identifiers.items():
                if key != "lease_epoch":
                    self.assertNotIn(str(private_value), serialized)
            self.assertNotIn("request_id", serialized)
            self.assertNotIn("action_id", serialized)

    def test_corrupt_audit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as sandbox:
            state = Path(sandbox) / "root-role-audit.json"
            state.write_text("not-json", encoding="utf-8")
            with self.assertRaisesRegex(guard.GuardInputError, "corrupt"):
                guard.evaluate_action(
                    request("receive_owner_intent"),
                    state_file=state,
                )

    def test_cli_returns_machine_readable_denial(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(MODULE),
                "--request",
                "-",
                "evaluate",
            ],
            input=json.dumps(request("run_tests")),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        response = json.loads(completed.stdout)
        self.assertEqual("DENY", response["result"]["decision"])
        self.assertEqual("TASK_EXECUTION", response["result"]["classification"])


class RootRoleControlCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = tempfile.TemporaryDirectory(dir=ROOT.parent)
        self.state = Path(self.sandbox.name) / "state"
        initialized = subprocess.run(
            [
                sys.executable,
                "-B",
                str(CONTROL_CLI),
                "--state-dir",
                str(self.state),
                "--policy-ledger",
                str(POLICY_LEDGER),
                "init",
                "--now",
                NOW,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, initialized.returncode, initialized.stderr)

    def tearDown(self) -> None:
        self.sandbox.cleanup()

    def classify(self, value: dict[str, object]) -> dict[str, object]:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(CONTROL_CLI),
                "--state-dir",
                str(self.state),
                "--policy-ledger",
                str(POLICY_LEDGER),
                "classify-root-action",
                "--request",
                "-",
            ],
            cwd=ROOT,
            input=json.dumps(value),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            0,
            completed.returncode,
            f"stdout={completed.stdout}\nstderr={completed.stderr}",
        )
        response = json.loads(completed.stdout)
        self.assertEqual("classify-root-action", response["operation"])
        self.assertTrue(response["result"]["dispatcher_enforcement_required"])
        self.assertFalse(response["result"]["runtime_enforcement_proven"])
        return response["result"]

    def test_cli_denies_missed_delegation_and_direct_worker_actions(self) -> None:
        for action in (
            "inspect_repository",
            "design_solution",
            "run_tests",
        ):
            with self.subTest(action=action):
                value = request(action)
                value["exception_receipt"] = execution_exception(action)
                result = self.classify(value)
                self.assertEqual("DENY", result["decision"])
                self.assertEqual(
                    "PREPARE_SUCCESSOR_HANDOFF", result["required_action"]
                )

    def test_cli_denies_send_message_completion_and_receiptless_capacity(
        self,
    ) -> None:
        completion = self.classify(
            request(
                "synthesize_worker_evidence",
                target_status="implemented",
                evidence=[{"kind": "send_message", "verified": True}],
            )
        )
        capacity = self.classify(request("refill_capacity"))
        self.assertEqual("UNTRUTHFUL_STATUS_FORBIDDEN", completion["reason_code"])
        self.assertEqual("EXACT_LAUNCH_RECEIPT_REQUIRED", capacity["reason_code"])

    def test_cli_accepts_only_exact_live_nondelegable_exception(self) -> None:
        valid = request(
            "run_tests",
            delegable_worker_available=False,
            exception_receipt=execution_exception("run_tests"),
        )
        self.assertEqual("ALLOW", self.classify(valid)["decision"])

        stale = dict(valid)
        stale["request_id"] = "request-run-tests-stale"
        stale["action_id"] = "action-run-tests-stale"
        stale["exception_receipt"] = execution_exception(
            "run_tests",
            action_id="action-run-tests-stale",
            issued_at="2026-07-28T17:00:00Z",
            expires_at="2026-07-28T17:05:00Z",
        )
        wrong_scope = dict(valid)
        wrong_scope["request_id"] = "request-run-tests-scope"
        wrong_scope["exception_receipt"] = execution_exception(
            "run_tests", scope_id="different-scope"
        )
        self.assertEqual("DENY", self.classify(stale)["decision"])
        self.assertEqual("DENY", self.classify(wrong_scope)["decision"])

    def test_cli_rejects_fabricated_owner_gate_evidence(self) -> None:
        fabricated = request(
            "notify_owner",
            evidence=[
                {
                    "kind": "owner_gate",
                    "verified": True,
                    "decision_request_id": "decision-not-in-ledger",
                    "route": "OWNER_GATE",
                    "owner_prompt_required": True,
                }
            ],
        )
        result = self.classify(fabricated)
        self.assertEqual("DENY", result["decision"])
        self.assertEqual("VERIFIED_OWNER_GATE_REQUIRED", result["reason_code"])
        self.assertFalse(result["owner_notification_authorized"])


if __name__ == "__main__":
    unittest.main()
