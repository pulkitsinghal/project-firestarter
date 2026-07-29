from __future__ import annotations

import ast
import base64
import copy
import hashlib
import hmac
import json
import multiprocessing
import os
import tempfile
import threading
import unittest
from pathlib import Path

from tools.service_supervisor.permits import (
    HANDOFF_RECEIPT_KEYS,
    HANDOFF_RECEIPT_VERSION,
    PERMIT_POLICY_VERSION,
    PLAN_KEYS,
    RESULT_KEYS,
    AuthorizationTelemetry,
    EnvelopeError,
    PermitRefusal,
    PermitStateError,
    PermitVerifier,
    build_plan,
    canonical_json_bytes,
    compute_plan_digest,
    handoff_receipt_signing_bytes,
    load_contract_pin,
    permit_signing_bytes,
    validate_handoff_receipt,
    validate_plan,
    validate_result,
)

NOW = 1_700_000_000
KEY = b"k" * 32
RECEIPT_KEY = b"r" * 32
SYNTHETIC_RECEIPT_KEY = b"synthetic-receipt-test-key-32bytes!"
SCHEMA_DIGEST = "a424f6a5b73641bdc6bdafc3411d49f7a239c663cbb0dd62eea665cfb6d76d97"
CATALOG_DIGEST = "6d0b7a440c2f6758b0b01482a5a508dba12b8c191938949854ad1189718fa5f1"
VERIFIER_ARTIFACT_DIGEST = "c" * 64
CONTRACT_PIN_DIGEST = "d" * 64


def launchd_steps() -> list[dict]:
    resource = "launchd:gui/501:com.local-ai.synthetic-launchd"
    health = {
        "kind": "http",
        "method": "GET",
        "url": "http://127.0.0.1:11500/healthz",
        "expect": {"kind": "status-2xx"},
        "timeout_ms": 5000,
        "interval_ms": 100,
    }
    return [
        {
            "sequence": 1,
            "service_id": "router",
            "adapter": "launchd",
            "operation": "bootstrap",
            "resource_key": resource,
            "argv": [
                "/bin/launchctl",
                "bootstrap",
                "gui/501",
                "/opt/local-ai/synthetic/com.local-ai.synthetic-launchd.plist",
            ],
            "http_request": None,
            "readiness": health,
            "rollback": {
                "operation": "bootout",
                "argv": [
                    "/bin/launchctl",
                    "bootout",
                    "gui/501/com.local-ai.synthetic-launchd",
                ],
                "http_request": None,
            },
        }
    ]


def all_adapter_steps() -> list[dict]:
    steps = launchd_steps()
    steps.extend(
        [
            {
                "sequence": 2,
                "service_id": "recall",
                "adapter": "docker-compose",
                "operation": "start",
                "resource_key": "compose:local-ai:recall",
                "argv": [
                    "/opt/homebrew/bin/docker",
                    "compose",
                    "--project-name",
                    "local-ai",
                    "--file",
                    "/opt/local-ai/compose.yml",
                    "start",
                    "recall",
                ],
                "http_request": None,
                "readiness": {
                    "kind": "http",
                    "method": "GET",
                    "url": "http://127.0.0.1:11520/health",
                    "expect": {"kind": "status-2xx"},
                    "timeout_ms": 5000,
                    "interval_ms": 100,
                },
                "rollback": {
                    "operation": "stop",
                    "argv": [
                        "/opt/homebrew/bin/docker",
                        "compose",
                        "--project-name",
                        "local-ai",
                        "--file",
                        "/opt/local-ai/compose.yml",
                        "stop",
                        "recall",
                    ],
                    "http_request": None,
                },
            },
            {
                "sequence": 3,
                "service_id": "ollama-host",
                "adapter": "ollama",
                "operation": "load",
                "resource_key": "ollama:qwen2.5",
                "argv": None,
                "http_request": {
                    "method": "POST",
                    "url": "http://127.0.0.1:11434/api/generate",
                    "json": {
                        "model": "qwen2.5",
                        "keep_alive": "5m",
                        "stream": False,
                    },
                },
                "readiness": {
                    "kind": "http",
                    "method": "GET",
                    "url": "http://127.0.0.1:11434/api/tags",
                    "expect": {
                        "kind": "ollama-model-resident",
                        "model": "qwen2.5",
                    },
                    "timeout_ms": 5000,
                    "interval_ms": 100,
                },
                "rollback": {
                    "operation": "unload",
                    "argv": None,
                    "http_request": {
                        "method": "POST",
                        "url": "http://127.0.0.1:11434/api/generate",
                        "json": {"model": "qwen2.5", "keep_alive": 0},
                    },
                },
            },
        ]
    )
    return steps


def plan(steps: list[dict] | None = None) -> dict:
    return build_plan(
        target_service_id="router",
        intent="ensure-ready",
        dry_run=True,
        steps=copy.deepcopy(steps or all_adapter_steps()),
    )


def redigest(value: dict) -> dict:
    value["plan_digest"] = compute_plan_digest(value)
    return value


def scope(value: dict, phase: str) -> tuple[list[str], list[str]]:
    if phase == "apply":
        selected = value["steps"]
        operations = [step["operation"] for step in selected]
    else:
        selected = [step for step in value["steps"] if step["rollback"] is not None]
        operations = [step["rollback"]["operation"] for step in selected]
    return (
        sorted(set(operations)),
        sorted({step["adapter"] for step in selected}),
    )


def signed_permit(
    value: dict,
    *,
    nonce: str = "abcdefghijklmnopqrstuv",
    phase: str = "apply",
    issued_at: int = NOW - 1,
    expires_at: int = NOW + 60,
    **changes,
) -> dict:
    actions, adapters = scope(value, phase)
    permit = {
        "schema_version": 1,
        "kind": "execution-permit",
        "policy_version": PERMIT_POLICY_VERSION,
        "permit_id": f"permit-{phase}",
        "authorization_phase": phase,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "nonce": nonce,
        "key_id": "pm-primary",
        "plan_digest": value["plan_digest"],
        "target_service_id": value["target_service_id"],
        "intent": value["intent"],
        "actions": actions,
        "adapter_set": adapters,
        "producer_schema_digest": SCHEMA_DIGEST,
        "catalog_digest": CATALOG_DIGEST,
        "executor_generation": 7,
        "state_generation": 9,
    }
    permit.update(changes)
    permit["signature"] = hmac.new(
        KEY, permit_signing_bytes(permit), hashlib.sha256
    ).hexdigest()
    return permit


def verifier(
    state_path: Path,
    *,
    telemetry: AuthorizationTelemetry | None = None,
    now: int = NOW,
) -> PermitVerifier:
    return PermitVerifier(
        state_path,
        {"pm-primary": KEY},
        expected_producer_schema_digest=SCHEMA_DIGEST,
        expected_catalog_digest=CATALOG_DIGEST,
        expected_executor_generation=7,
        expected_state_generation=9,
        expected_plan_digests={
            ("router", "ensure-ready"): plan()["plan_digest"]
        },
        receipt_key_id="firestarter-handoff",
        receipt_signing_key=RECEIPT_KEY,
        verifier_instance_id="firestarter-test-instance",
        verifier_artifact_digest=VERIFIER_ARTIFACT_DIGEST,
        contract_pin_digest=CONTRACT_PIN_DIGEST,
        clock=lambda: now,
        telemetry=telemetry,
    )


def validate_receipt(receipt: dict, value: dict) -> dict:
    actions, adapters = scope(value, str(receipt["authorization_phase"]))
    return validate_handoff_receipt(
        receipt,
        {"firestarter-handoff": RECEIPT_KEY},
        expected_target_service_id=value["target_service_id"],
        expected_intent=value["intent"],
        expected_authorization_phase=receipt["authorization_phase"],
        expected_plan_digest=value["plan_digest"],
        expected_actions=actions,
        expected_adapter_set=adapters,
        expected_producer_schema_digest=SCHEMA_DIGEST,
        expected_catalog_digest=CATALOG_DIGEST,
        expected_executor_generation=7,
        expected_state_generation=9,
        expected_verifier_instance_id="firestarter-test-instance",
        expected_verifier_artifact_digest=VERIFIER_ARTIFACT_DIGEST,
        expected_contract_pin_digest=CONTRACT_PIN_DIGEST,
        clock=lambda: NOW,
    )


def expected_receipt_nonce(permit_fingerprint: str) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(
            RECEIPT_KEY,
            b"execution-handoff-receipt-nonce\x00"
            + permit_fingerprint.encode("ascii"),
            hashlib.sha256,
        ).digest()
    ).rstrip(b"=").decode("ascii")


def process_verify_worker(state: str, value: dict, permit: dict, results) -> None:
    try:
        decision = verifier(Path(state)).verify_and_consume(value, permit)
        results.put(decision["decision"])
    except PermitRefusal as exc:
        results.put(exc.code)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover - diagnostic only
        results.put(type(exc).__name__)


class PlanEnvelopeTests(unittest.TestCase):
    def test_exact_plan_contract_and_digest_are_deterministic(self) -> None:
        first = plan()
        second = plan()
        self.assertEqual(first, second)
        self.assertEqual(PLAN_KEYS, frozenset(first))
        self.assertEqual("local-ai-adapter-plan", first["kind"])
        self.assertEqual("0.1.0", first["supervisor_contract_version"])
        self.assertTrue(first["dry_run"])
        self.assertEqual(first["plan_digest"], compute_plan_digest(first))
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))

    def test_all_three_adapter_shapes_validate(self) -> None:
        value = validate_plan(plan())
        self.assertEqual(
            ["launchd", "docker-compose", "ollama"],
            [step["adapter"] for step in value["steps"]],
        )
        indefinite = plan()
        indefinite["steps"][2]["http_request"]["json"]["keep_alive"] = "-1"
        redigest(indefinite)
        self.assertEqual(
            "-1",
            validate_plan(indefinite)["steps"][2]["http_request"]["json"][
                "keep_alive"
            ],
        )

    def test_noop_complete_stop_plan_validates_but_cannot_authorize_handoff(
        self,
    ) -> None:
        value = build_plan(
            target_service_id="router",
            intent="complete-stop",
            dry_run=True,
            steps=[],
        )
        self.assertEqual([], validate_plan(value)["steps"])
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            PermitRefusal, "PLAN_HAS_NO_ACTIONS"
        ):
            verifier(Path(directory) / "state.sqlite3").verify_and_consume(
                value, signed_permit(value)
            )

    def test_unknown_adapter_and_operation_fail_closed(self) -> None:
        for key, replacement, code in (
            ("adapter", "shell", "UNKNOWN_ADAPTER"),
            ("operation", "start;rm", "UNKNOWN_OPERATION"),
        ):
            value = plan()
            value["steps"][0][key] = replacement
            redigest(value)
            with self.subTest(key=key), self.assertRaisesRegex(EnvelopeError, code):
                validate_plan(value)

    def test_argv_path_and_url_injection_fail_closed(self) -> None:
        mutations = [
            (1, "argv", 7, "recall;rm"),
            (1, "argv", 5, "/opt/local-ai/../secret.yml"),
            (0, "argv", 3, "/tmp/router.plist"),
        ]
        for step_index, field, token_index, replacement in mutations:
            value = plan()
            value["steps"][step_index][field][token_index] = replacement
            redigest(value)
            with self.subTest(replacement=replacement), self.assertRaises(
                EnvelopeError
            ):
                validate_plan(value)

        for replacement in (
            "http://0.0.0.0:11434/api/generate",
            "http://127.0.0.1:11434/api/generate?model=evil",
            "https://127.0.0.1:11434/api/generate",
        ):
            value = plan()
            value["steps"][2]["http_request"]["url"] = replacement
            redigest(value)
            with self.subTest(replacement=replacement), self.assertRaisesRegex(
                EnvelopeError, "UNSAFE_OLLAMA_URL"
            ):
                validate_plan(value)

        value = plan()
        value["steps"][0]["argv"][2] = "system"
        value["steps"][0]["resource_key"] = (
            "launchd:system:com.local-ai.synthetic-launchd"
        )
        redigest(value)
        with self.assertRaises(EnvelopeError):
            validate_plan(value)
        value = plan()
        value["steps"][1]["readiness"]["url"] = (
            "http://127.0.0.1:11520/%2e%2e/private"
        )
        redigest(value)
        with self.assertRaisesRegex(EnvelopeError, "UNSAFE_READINESS_URL"):
            validate_plan(value)

    def test_duplicate_and_out_of_order_steps_refuse(self) -> None:
        duplicate_steps = launchd_steps()
        duplicate = copy.deepcopy(duplicate_steps[0])
        duplicate["sequence"] = 2
        duplicate_steps.append(duplicate)
        with self.assertRaisesRegex(EnvelopeError, "DUPLICATE_PLAN_STEP"):
            plan(duplicate_steps)

        value = plan()
        value["steps"][0], value["steps"][1] = value["steps"][1], value["steps"][0]
        redigest(value)
        with self.assertRaisesRegex(EnvelopeError, "NON_CONTIGUOUS_STEP_SEQUENCE"):
            validate_plan(value)

    def test_digest_mismatch_and_unknown_top_level_field_refuse(self) -> None:
        value = plan()
        value["plan_digest"] = "0" * 64
        with self.assertRaisesRegex(EnvelopeError, "PLAN_DIGEST_MISMATCH"):
            validate_plan(value)
        value = plan()
        value["shell"] = "launchctl kickstart"
        redigest(value)
        with self.assertRaisesRegex(EnvelopeError, "INVALID_PLAN_KEYS"):
            validate_plan(value)

    def test_rollback_is_typed_inverse_and_never_shell(self) -> None:
        value = plan()
        value["steps"][0]["rollback"]["operation"] = "kickstart"
        redigest(value)
        with self.assertRaisesRegex(EnvelopeError, "ROLLBACK_OPERATION_MISMATCH"):
            validate_plan(value)
        value = plan()
        value["steps"][1]["rollback"]["argv"].append("&&")
        redigest(value)
        with self.assertRaisesRegex(EnvelopeError, "INVALID_COMPOSE_ARGV"):
            validate_plan(value)


class ResultEnvelopeTests(unittest.TestCase):
    def result(self, value: dict, **changes) -> dict:
        result = {
            "schema_version": 1,
            "kind": "local-ai-adapter-result",
            "plan_digest": value["plan_digest"],
            "status": "dry-run",
            "completed_steps": [],
            "failed_step": None,
            "readiness_proved": False,
            "rollback_status": "not-run",
            "error": None,
        }
        result.update(changes)
        return result

    def test_dry_run_result_is_exact_and_content_free(self) -> None:
        value = plan()
        result = validate_result(self.result(value), value)
        self.assertEqual(RESULT_KEYS, frozenset(result))
        self.assertEqual("dry-run", result["status"])

    def test_malicious_result_and_digest_mismatch_refuse(self) -> None:
        value = plan()
        malicious = self.result(value)
        malicious["stdout"] = "secret output"
        with self.assertRaisesRegex(EnvelopeError, "INVALID_RESULT_KEYS"):
            validate_result(malicious, value)
        mismatch = self.result(value, plan_digest="0" * 64)
        with self.assertRaisesRegex(EnvelopeError, "RESULT_PLAN_SCOPE_MISMATCH"):
            validate_result(mismatch, value)
        unsafe_error = self.result(
            value,
            status="failed",
            failed_step=1,
            rollback_status="failed",
            error={
                "code": "synthetic-failure",
                "message": "see http://evil.test/token",
            },
        )
        with self.assertRaisesRegex(EnvelopeError, "INVALID_ERROR_MESSAGE"):
            validate_result(unsafe_error, value)

    def test_partial_readiness_cannot_claim_success(self) -> None:
        value = plan()
        partial = self.result(
            value,
            status="succeeded",
            completed_steps=list(range(1, len(value["steps"]) + 1)),
            readiness_proved=False,
            rollback_status="not-needed",
        )
        with self.assertRaisesRegex(
            EnvelopeError, "PARTIAL_READINESS_CANNOT_SUCCEED"
        ):
            validate_result(partial, value)

    def test_rollback_success_and_failure_are_distinct(self) -> None:
        value = plan()
        rolled_back = self.result(
            value,
            status="rolled-back",
            completed_steps=[1],
            failed_step=2,
            rollback_status="succeeded",
            error={
                "code": "readiness-timeout",
                "message": "synthetic readiness proof timed out",
            },
        )
        self.assertEqual(
            "rolled-back", validate_result(rolled_back, value)["status"]
        )
        failed = self.result(
            value,
            status="failed",
            completed_steps=[1],
            failed_step=2,
            rollback_status="failed",
            error={
                "code": "rollback-failed",
                "message": "synthetic rollback failed",
            },
        )
        self.assertEqual("failed", validate_result(failed, value)["status"])
        inconsistent = copy.deepcopy(failed)
        inconsistent["rollback_status"] = "succeeded"
        with self.assertRaisesRegex(
            EnvelopeError, "ROLLBACK_FAILURE_INCONSISTENT"
        ):
            validate_result(inconsistent, value)

    def test_noncompensable_completed_action_cannot_claim_rolled_back(self) -> None:
        steps = all_adapter_steps()
        steps[0]["rollback"] = None
        value = plan(steps)
        result = self.result(
            value,
            status="rolled-back",
            completed_steps=[1],
            failed_step=2,
            rollback_status="succeeded",
            error={
                "code": "rollback-incomplete",
                "message": "synthetic rollback was incomplete",
            },
        )
        with self.assertRaisesRegex(
            EnvelopeError, "NONCOMPENSABLE_STEP_CANNOT_ROLL_BACK"
        ):
            validate_result(result, value)

    def test_completed_steps_must_be_ordered_prefix(self) -> None:
        value = plan()
        failed = self.result(
            value,
            status="failed",
            completed_steps=[1, 3],
            failed_step=4,
            rollback_status="failed",
            error={
                "code": "synthetic-failure",
                "message": "synthetic lifecycle proof failed",
            },
        )
        with self.assertRaisesRegex(EnvelopeError, "INVALID_COMPLETED_STEPS"):
            validate_result(failed, value)


class PermitVerificationTests(unittest.TestCase):
    def test_absent_permit_refuses_and_exact_permit_authorizes_handoff_only(self) -> None:
        value = plan()
        with tempfile.TemporaryDirectory() as directory:
            check = verifier(Path(directory) / "permits.sqlite3")
            with self.assertRaisesRegex(EnvelopeError, "INVALID_PERMIT_KEYS"):
                check.verify_and_consume(value, None)
            receipt = check.verify_and_consume(
                value, signed_permit(value, nonce="abcdefghijklmnopqrstuw")
            )
        self.assertEqual("AUTHORIZED_FOR_EXECUTOR_HANDOFF", receipt["decision"])
        self.assertEqual(HANDOFF_RECEIPT_KEYS, frozenset(receipt))
        self.assertEqual(HANDOFF_RECEIPT_VERSION, receipt["receipt_version"])
        self.assertFalse(receipt["rollback_authorized"])
        self.assertEqual("firestarter-test-instance", receipt["verifier_instance_id"])
        self.assertEqual(
            expected_receipt_nonce(receipt["permit_fingerprint"]),
            receipt["receipt_nonce"],
        )
        self.assertEqual(NOW, receipt["issued_at"])
        self.assertEqual(NOW + 60, receipt["expires_at"])
        self.assertEqual(
            ["docker-compose", "launchd", "ollama"], receipt["adapter_set"]
        )
        expected_signature = hmac.new(
            RECEIPT_KEY,
            handoff_receipt_signing_bytes(receipt),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(expected_signature, receipt["signature"])
        self.assertEqual(receipt, validate_receipt(receipt, value))

    def test_handoff_receipt_tampering_is_detectable_and_permit_key_cannot_sign_it(
        self,
    ) -> None:
        value = plan()
        with tempfile.TemporaryDirectory() as directory:
            receipt = verifier(
                Path(directory) / "state.sqlite3"
            ).verify_and_consume(value, signed_permit(value))
        tampered = copy.deepcopy(receipt)
        tampered["target_service_id"] = "other-service"
        receipt_signature = hmac.new(
            RECEIPT_KEY,
            handoff_receipt_signing_bytes(tampered),
            hashlib.sha256,
        ).hexdigest()
        permit_key_signature = hmac.new(
            KEY,
            handoff_receipt_signing_bytes(receipt),
            hashlib.sha256,
        ).hexdigest()
        self.assertNotEqual(receipt["signature"], receipt_signature)
        self.assertNotEqual(receipt["signature"], permit_key_signature)
        with self.assertRaisesRegex(
            PermitRefusal, "TAMPERED_HANDOFF_RECEIPT"
        ):
            validate_receipt(tampered, value)

    def test_handoff_receipt_scope_time_and_key_fail_closed(self) -> None:
        value = plan()
        with tempfile.TemporaryDirectory() as directory:
            receipt = verifier(
                Path(directory) / "state.sqlite3"
            ).verify_and_consume(value, signed_permit(value))
        with self.assertRaisesRegex(
            PermitRefusal, "WRONG_HANDOFF_RECEIPT_SCOPE"
        ):
            validate_handoff_receipt(
                receipt,
                {"firestarter-handoff": RECEIPT_KEY},
                expected_target_service_id="other-service",
                expected_intent=value["intent"],
                expected_authorization_phase="apply",
                expected_plan_digest=value["plan_digest"],
                expected_actions=receipt["actions"],
                expected_adapter_set=receipt["adapter_set"],
                expected_producer_schema_digest=SCHEMA_DIGEST,
                expected_catalog_digest=CATALOG_DIGEST,
                expected_executor_generation=7,
                expected_state_generation=9,
                expected_verifier_instance_id="firestarter-test-instance",
                expected_verifier_artifact_digest=VERIFIER_ARTIFACT_DIGEST,
                expected_contract_pin_digest=CONTRACT_PIN_DIGEST,
                clock=lambda: NOW,
            )
        with self.assertRaisesRegex(PermitRefusal, "UNTRUSTED_RECEIPT_KEY"):
            validate_handoff_receipt(
                receipt,
                {},
                expected_target_service_id=value["target_service_id"],
                expected_intent=value["intent"],
                expected_authorization_phase="apply",
                expected_plan_digest=value["plan_digest"],
                expected_actions=receipt["actions"],
                expected_adapter_set=receipt["adapter_set"],
                expected_producer_schema_digest=SCHEMA_DIGEST,
                expected_catalog_digest=CATALOG_DIGEST,
                expected_executor_generation=7,
                expected_state_generation=9,
                expected_verifier_instance_id="firestarter-test-instance",
                expected_verifier_artifact_digest=VERIFIER_ARTIFACT_DIGEST,
                expected_contract_pin_digest=CONTRACT_PIN_DIGEST,
                clock=lambda: NOW,
            )
        with self.assertRaisesRegex(PermitRefusal, "STALE_HANDOFF_RECEIPT"):
            validate_handoff_receipt(
                receipt,
                {"firestarter-handoff": RECEIPT_KEY},
                expected_target_service_id=value["target_service_id"],
                expected_intent=value["intent"],
                expected_authorization_phase="apply",
                expected_plan_digest=value["plan_digest"],
                expected_actions=receipt["actions"],
                expected_adapter_set=receipt["adapter_set"],
                expected_producer_schema_digest=SCHEMA_DIGEST,
                expected_catalog_digest=CATALOG_DIGEST,
                expected_executor_generation=7,
                expected_state_generation=9,
                expected_verifier_instance_id="firestarter-test-instance",
                expected_verifier_artifact_digest=VERIFIER_ARTIFACT_DIGEST,
                expected_contract_pin_digest=CONTRACT_PIN_DIGEST,
                clock=lambda: NOW + 60,
            )

    def test_receipt_and_pm_permit_keys_must_be_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            ValueError, "receipt and PM permit keys must be distinct"
        ):
            PermitVerifier(
                Path(directory) / "state.sqlite3",
                {"pm-primary": KEY},
                expected_producer_schema_digest=SCHEMA_DIGEST,
                expected_catalog_digest=CATALOG_DIGEST,
                expected_executor_generation=7,
                expected_state_generation=9,
                expected_plan_digests={
                    ("router", "ensure-ready"): plan()["plan_digest"]
                },
                receipt_key_id="firestarter-handoff",
                receipt_signing_key=KEY,
                verifier_instance_id="firestarter-test-instance",
                verifier_artifact_digest=VERIFIER_ARTIFACT_DIGEST,
                contract_pin_digest=CONTRACT_PIN_DIGEST,
            )

    def test_unsigned_local_ai_permit_fixture_is_never_authority(self) -> None:
        value = plan()
        untrusted = {
            "schema_version": 1,
            "kind": "pm-proxy-execution-permit",
            "permit_id": "permit_00000001",
            "plan_digest": value["plan_digest"],
            "service_ids": [value["target_service_id"]],
            "intents": [value["intent"]],
            "issued_at": NOW - 1,
            "expires_at": NOW + 60,
        }
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            EnvelopeError, "INVALID_PERMIT_KEYS"
        ):
            verifier(Path(directory) / "state.sqlite3").verify_and_consume(
                value, untrusted
            )

    def test_stale_future_tampered_wrong_scope_and_wrong_generation_refuse(self) -> None:
        value = plan()
        cases = [
            (
                signed_permit(value, expires_at=NOW),
                "STALE_PERMIT",
            ),
            (
                signed_permit(
                    value,
                    issued_at=NOW + 31,
                    expires_at=NOW + 61,
                ),
                "PERMIT_NOT_YET_VALID",
            ),
            (
                signed_permit(
                    value,
                    issued_at=NOW - 1,
                    expires_at=NOW + 400,
                ),
                "INVALID_PERMIT_WINDOW",
            ),
            (
                signed_permit(value, plan_digest="0" * 64),
                "WRONG_PERMIT_SCOPE",
            ),
            (
                signed_permit(value, target_service_id="other-service"),
                "WRONG_PERMIT_SCOPE",
            ),
            (
                signed_permit(value, intent="restart"),
                "WRONG_PERMIT_SCOPE",
            ),
            (
                signed_permit(value, actions=["load"]),
                "WRONG_PERMIT_SCOPE",
            ),
            (
                signed_permit(value, adapter_set=["ollama"]),
                "WRONG_PERMIT_SCOPE",
            ),
            (
                signed_permit(value, policy_version="pm-execution-permit/0"),
                "WRONG_POLICY_VERSION",
            ),
            (
                signed_permit(value, executor_generation=8),
                "WRONG_AUTHORITY_GENERATION",
            ),
        ]
        tampered = signed_permit(value)
        tampered["adapter_set"] = ["launchd"]
        cases.append((tampered, "TAMPERED_PERMIT"))
        for index, (permit, code) in enumerate(cases):
            with tempfile.TemporaryDirectory() as directory:
                check = verifier(Path(directory) / f"state-{index}.sqlite3")
                with self.subTest(code=code), self.assertRaisesRegex(
                    PermitRefusal, code
                ):
                    check.verify_and_consume(value, permit)

    def test_catalog_derived_digest_blocks_validly_reordered_plan(self) -> None:
        value = plan()
        reordered = copy.deepcopy(value)
        reordered["steps"][0], reordered["steps"][1] = (
            reordered["steps"][1],
            reordered["steps"][0],
        )
        for sequence, step in enumerate(reordered["steps"], start=1):
            step["sequence"] = sequence
        redigest(reordered)
        validate_plan(reordered)
        permit = signed_permit(
            reordered, nonce="abcdefghijklmnopqrstuy"
        )
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            PermitRefusal, "PLAN_NOT_CATALOG_DERIVED"
        ):
            verifier(Path(directory) / "state.sqlite3").verify_and_consume(
                reordered, permit
            )

    def test_clock_skew_boundary_is_bounded(self) -> None:
        value = plan()
        permit = signed_permit(
            value,
            issued_at=NOW + 30,
            expires_at=NOW + 60,
        )
        with tempfile.TemporaryDirectory() as directory:
            decision = verifier(Path(directory) / "state.sqlite3").verify_and_consume(
                value, permit
            )
        self.assertEqual("AUTHORIZED_FOR_EXECUTOR_HANDOFF", decision["decision"])

    def test_nonce_is_single_use_across_restart(self) -> None:
        value = plan()
        permit = signed_permit(value)
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.sqlite3"
            verifier(state).verify_and_consume(value, permit)
            with self.assertRaisesRegex(PermitRefusal, "REPLAYED_PERMIT"):
                verifier(state).verify_and_consume(value, permit)
            self.assertEqual(0o600, stat_mode(state))

    def test_same_nonce_with_different_signed_permit_is_conflict(self) -> None:
        value = plan()
        first = signed_permit(value)
        conflict = signed_permit(value, permit_id="permit-conflict")
        with tempfile.TemporaryDirectory() as directory:
            check = verifier(Path(directory) / "state.sqlite3")
            check.verify_and_consume(value, first)
            with self.assertRaisesRegex(PermitRefusal, "CONFLICTING_PERMIT"):
                check.verify_and_consume(value, conflict)

    def test_second_nonce_cannot_reauthorize_same_plan_generation(self) -> None:
        value = plan()
        first = signed_permit(value)
        second = signed_permit(
            value,
            nonce="abcdefghijklmnopqrstuz",
            permit_id="permit-second",
        )
        with tempfile.TemporaryDirectory() as directory:
            check = verifier(Path(directory) / "state.sqlite3")
            check.verify_and_consume(value, first)
            with self.assertRaisesRegex(PermitRefusal, "CONFLICTING_PERMIT"):
                check.verify_and_consume(value, second)

    def test_concurrent_single_use_race_has_exactly_one_winner(self) -> None:
        value = plan()
        permit = signed_permit(value)
        decisions: list[dict] = []
        refusals: list[str] = []
        barrier = threading.Barrier(41)
        with tempfile.TemporaryDirectory() as directory:
            check = verifier(Path(directory) / "state.sqlite3")

            def worker() -> None:
                barrier.wait(timeout=5)
                try:
                    decisions.append(check.verify_and_consume(value, permit))
                except PermitRefusal as exc:
                    refusals.append(exc.code)

            threads = [threading.Thread(target=worker) for _ in range(40)]
            for thread in threads:
                thread.start()
            barrier.wait(timeout=5)
            for thread in threads:
                thread.join(timeout=10)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(1, len(decisions))
        self.assertEqual(39, refusals.count("REPLAYED_PERMIT"))

    def test_cross_process_single_use_race_has_exactly_one_winner(self) -> None:
        value = plan()
        permit = signed_permit(value)
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as directory:
            state = str(Path(directory) / "state.sqlite3")
            results = context.Queue()
            processes = [
                context.Process(
                    target=process_verify_worker,
                    args=(state, value, permit, results),
                )
                for _ in range(12)
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=15)
            self.assertTrue(all(not process.is_alive() for process in processes))
            outcomes = [results.get(timeout=2) for _ in processes]
            results.close()
        self.assertEqual(1, outcomes.count("AUTHORIZED_FOR_EXECUTOR_HANDOFF"))
        self.assertEqual(11, outcomes.count("REPLAYED_PERMIT"))

    def test_transaction_failure_rolls_back_nonce_for_crash_recovery(self) -> None:
        value = plan()
        permit = signed_permit(value)
        calls = 0

        def crash_once() -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("synthetic crash")

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.sqlite3"
            check = verifier(state)
            check._after_nonce_recorded = crash_once
            with self.assertRaisesRegex(
                PermitStateError, "NONCE_CONSUMPTION_FAILED"
            ):
                check.verify_and_consume(value, permit)
            decision = verifier(state).verify_and_consume(value, permit)
        self.assertEqual("AUTHORIZED_FOR_EXECUTOR_HANDOFF", decision["decision"])

    def test_revocation_is_durable_and_idempotent(self) -> None:
        value = plan()
        permit = signed_permit(value)
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.sqlite3"
            check = verifier(state)
            check.revoke(permit["nonce"], reason_code="scope-withdrawn")
            check.revoke(permit["nonce"], reason_code="scope-withdrawn")
            with self.assertRaisesRegex(PermitRefusal, "REVOKED_PERMIT"):
                verifier(state).verify_and_consume(value, permit)

    def test_rollback_requires_a_separate_phase_and_nonce(self) -> None:
        value = plan()
        apply_permit = signed_permit(value)
        rollback_permit = signed_permit(
            value,
            phase="rollback",
            nonce="abcdefghijklmnopqrstux",
        )
        with tempfile.TemporaryDirectory() as directory:
            check = verifier(Path(directory) / "state.sqlite3")
            apply_receipt = check.verify_and_consume(value, apply_permit)
            with self.assertRaisesRegex(
                PermitRefusal, "WRONG_AUTHORIZATION_PHASE"
            ):
                check.verify_and_consume(
                    value, apply_permit, authorization_phase="rollback"
                )
            decision = check.verify_and_consume(
                value, rollback_permit, authorization_phase="rollback"
            )
        self.assertTrue(decision["rollback_authorized"])
        self.assertEqual(["bootout", "stop", "unload"], decision["actions"])
        self.assertNotEqual(
            apply_receipt["receipt_nonce"], decision["receipt_nonce"]
        )

    def test_snapshot_is_deterministic_and_excludes_raw_nonce(self) -> None:
        value = plan()
        permit = signed_permit(value)
        with tempfile.TemporaryDirectory() as directory:
            first = verifier(Path(directory) / "one.sqlite3")
            second = verifier(Path(directory) / "two.sqlite3")
            first.verify_and_consume(value, permit)
            second.verify_and_consume(value, permit)
            first_snapshot = first.deterministic_snapshot_bytes()
            second_snapshot = second.deterministic_snapshot_bytes()
        self.assertEqual(first_snapshot, second_snapshot)
        self.assertNotIn(permit["nonce"].encode(), first_snapshot)
        self.assertNotIn(permit["signature"].encode(), first_snapshot)

    def test_symlink_and_corrupt_state_refuse(self) -> None:
        with self.assertRaisesRegex(
            PermitStateError, "STATE_PATH_MUST_BE_ABSOLUTE"
        ):
            verifier(Path("relative-state.sqlite3"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.sqlite3"
            target.write_bytes(b"")
            link = root / "link.sqlite3"
            link.symlink_to(target)
            with self.assertRaisesRegex(PermitStateError, "UNSAFE_STATE_PATH"):
                verifier(link)
            corrupt = root / "corrupt.sqlite3"
            corrupt.write_bytes(b"not a sqlite database")
            with self.assertRaises(PermitStateError):
                verifier(corrupt)
            insecure = root / "insecure.sqlite3"
            insecure.write_bytes(b"")
            insecure.chmod(0o644)
            with self.assertRaisesRegex(
                PermitStateError, "UNSAFE_STATE_PERMISSIONS"
            ):
                verifier(insecure)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            parent_link = root / "parent-link"
            parent_link.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaisesRegex(
                PermitStateError, "UNSAFE_STATE_PARENT"
            ):
                verifier(parent_link / "nested" / "state.sqlite3")

    def test_telemetry_is_exact_and_content_free(self) -> None:
        value = plan()
        permit = signed_permit(value)
        telemetry = AuthorizationTelemetry()
        with tempfile.TemporaryDirectory() as directory:
            check = verifier(
                Path(directory) / "state.sqlite3", telemetry=telemetry
            )
            check.verify_and_consume(value, permit)
            with self.assertRaises(PermitRefusal):
                check.verify_and_consume(value, permit)
        events = telemetry.events()
        expected_keys = {
            "schema_version",
            "event",
            "outcome",
            "reason_code",
            "target_service_id",
            "intent",
            "authorization_phase",
            "plan_digest",
            "adapter_set",
        }
        self.assertEqual(2, len(events))
        self.assertTrue(all(set(event) == expected_keys for event in events))
        serialized = canonical_json_bytes(events)
        for forbidden in (
            permit["nonce"],
            permit["signature"],
            "qwen2.5",
            "/opt/local-ai/synthetic",
            "11434",
        ):
            self.assertNotIn(forbidden.encode(), serialized)
        with self.assertRaisesRegex(ValueError, "content-free"):
            telemetry.record(
                outcome="REFUSED",
                reason_code="secret=/private/path",
                plan=value,
                adapter_set=["launchd"],
                authorization_phase="apply",
            )


class StaticSafetyTests(unittest.TestCase):
    def test_untrusted_synthetic_handoff_fixture_is_pinned_and_authentic(self) -> None:
        root = Path(__file__).resolve().parents[1]
        fixture = json.loads(
            (
                root
                / "compatibility"
                / "firestarter"
                / "execution-handoff-receipt-1.untrusted.synthetic.json"
            ).read_text()
        )
        self.assertEqual(
            hashlib.sha256((root / "permits.py").read_bytes()).hexdigest(),
            fixture["verifier_artifact_digest"],
        )
        self.assertEqual(
            hashlib.sha256(
                (root / "local-ai-contract-pin.json").read_bytes()
            ).hexdigest(),
            fixture["contract_pin_digest"],
        )
        validate_handoff_receipt(
            fixture,
            {"synthetic-handoff": SYNTHETIC_RECEIPT_KEY},
            expected_target_service_id="synthetic-ollama",
            expected_intent="ensure-ready",
            expected_authorization_phase="apply",
            expected_plan_digest=(
                "9099a1ad8f5d19a261243a29e13f0719"
                "f9663af3d7a28201adef99e76d7d3796"
            ),
            expected_actions=["bootstrap", "load", "start"],
            expected_adapter_set=["docker-compose", "launchd", "ollama"],
            expected_producer_schema_digest=SCHEMA_DIGEST,
            expected_catalog_digest=CATALOG_DIGEST,
            expected_executor_generation=1,
            expected_state_generation=1,
            expected_verifier_instance_id="firestarter-0.2-synthetic",
            expected_verifier_artifact_digest=fixture[
                "verifier_artifact_digest"
            ],
            expected_contract_pin_digest=fixture["contract_pin_digest"],
            clock=lambda: NOW,
        )

    def test_exact_merged_contract_pin_and_copied_fixtures_are_pinned(self) -> None:
        root = Path(__file__).resolve().parents[1]
        pin = load_contract_pin(root / "local-ai-contract-pin.json")
        self.assertEqual(
            "3986befb06106b66795444d54f8513ead83f76b0",
            pin["source_ref"],
        )
        copied = root / "compatibility" / "local-ai"
        pairs = (
            ("catalog_fixture_sha256", "service-lifecycle-catalog-1.synthetic.json"),
            (
                "observations_fixture_sha256",
                "service-lifecycle-observations-1.synthetic.json",
            ),
            ("plan_fixture_sha256", "service-lifecycle-plan-1.synthetic.json"),
            ("result_fixture_sha256", "service-lifecycle-result-1.synthetic.json"),
            (
                "untrusted_permit_fixture_sha256",
                "service-lifecycle-permit-1.untrusted.synthetic.json",
            ),
        )
        for digest_key, filename in pairs:
            with self.subTest(filename=filename):
                self.assertEqual(
                    pin[digest_key],
                    hashlib.sha256((copied / filename).read_bytes()).hexdigest(),
                )
        producer_plan = json.loads(
            (copied / "service-lifecycle-plan-1.synthetic.json").read_text()
        )
        producer_result = json.loads(
            (copied / "service-lifecycle-result-1.synthetic.json").read_text()
        )
        self.assertEqual(pin["canonical_plan_digest"], producer_plan["plan_digest"])
        self.assertEqual(
            pin["canonical_plan_digest"],
            validate_plan(producer_plan)["plan_digest"],
        )
        self.assertEqual("dry-run", validate_result(producer_result, producer_plan)["status"])

    def test_only_exact_regular_merged_contract_pin_loads(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        pinned = json.loads(
            (source_root / "local-ai-contract-pin.json").read_text()
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "pin.json"
            path.write_bytes(canonical_json_bytes(pinned))
            self.assertEqual(pinned, load_contract_pin(path))
            tampered = dict(pinned)
            tampered["source_ref"] = "c" * 40
            path.write_bytes(canonical_json_bytes(tampered))
            with self.assertRaisesRegex(EnvelopeError, "CONTRACT_PIN_MISMATCH"):
                load_contract_pin(path)
            link = root / "link.json"
            link.symlink_to(path)
            with self.assertRaisesRegex(EnvelopeError, "UNSAFE_CONTRACT_PIN"):
                load_contract_pin(link)

    def test_module_has_no_executor_or_network_surface(self) -> None:
        source_path = Path(__file__).resolve().parents[1] / "permits.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imports: set[str] = set()
        calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.add(node.func.attr)
        self.assertFalse(
            imports
            & {
                "subprocess",
                "socket",
                "http.client",
                "urllib.request",
                "docker",
            }
        )
        self.assertFalse(
            calls
            & {
                "system",
                "popen",
                "execv",
                "execve",
                "spawnl",
                "spawnv",
            }
        )

    def test_schema_top_level_keys_match_runtime(self) -> None:
        root = Path(__file__).resolve().parents[1]
        plan_schema = json.loads(
            (root / "lifecycle-plan.schema.json").read_text(encoding="utf-8")
        )
        result_schema = json.loads(
            (root / "lifecycle-result.schema.json").read_text(encoding="utf-8")
        )
        receipt_schema = json.loads(
            (root / "execution-handoff-receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(plan_schema["additionalProperties"])
        self.assertFalse(result_schema["additionalProperties"])
        self.assertEqual(PLAN_KEYS, frozenset(plan_schema["properties"]))
        self.assertEqual(RESULT_KEYS, frozenset(result_schema["properties"]))
        self.assertEqual(
            HANDOFF_RECEIPT_KEYS, frozenset(receipt_schema["properties"])
        )


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
