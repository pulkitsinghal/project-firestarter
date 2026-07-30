from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests.support import (
    BRIDGE,
    classify_request,
    config_verified_runtime_attestation,
    handback_request,
    iso,
    launch_request,
    make_fake_install,
    policy_rule_request,
    private_temp,
    recycle_request,
    write_json,
)
from tests.task_tool_stub import SyntheticTaskTool


class BridgeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = private_temp("pm-proxy-test-")
        self.cli = make_fake_install(self.root)
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.runtime_attestation = write_json(
            self.root / "runtime-attestation.json",
            config_verified_runtime_attestation(),
        )

    def run_bridge(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(BRIDGE),
            "--cli",
            str(self.cli),
            "--state-dir",
            str(self.state),
            *args,
        ]
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        return subprocess.run(command, text=True, capture_output=True, env=process_env, check=False)

    def parsed(self, completed: subprocess.CompletedProcess[str]) -> dict:
        raw = completed.stdout if completed.returncode == 0 else completed.stderr
        return json.loads(raw)

    def prepare(self, *, task_id: str = "task-1", prompt: str = "SYNTHETIC_EPHEMERAL_PROMPT_Ω"):
        recycle = write_json(self.root / f"{task_id}-recycle.json", recycle_request(request_id="recycle-" + task_id))
        launch = write_json(self.root / f"{task_id}-launch.json", launch_request(task_id=task_id, prompt=prompt))
        ticket = self.state / f"{task_id}.ticket.json"
        completed = self.run_bridge(
            "prepare-launch",
            "--recycle-request",
            str(recycle),
            "--launch-request",
            str(launch),
            "--ticket",
            str(ticket),
        )
        return completed, ticket

    def receipt(self, ticket: Path, *, now: str | None = None, external_id: str = "thread-synthetic"):
        return self.run_bridge(
            "record-launch-receipt",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            external_id,
            "--runtime-attestation",
            str(self.runtime_attestation),
            "--request-id",
            "receipt-1",
            "--now",
            now or iso(minutes=1),
        )

    def test_doctor_fails_for_missing_cli_locked_state_and_schema_mismatch(self):
        missing = subprocess.run(
            [
                sys.executable,
                str(BRIDGE),
                "--cli",
                str(self.root / "missing/orchestrator_control.py"),
                "--state-dir",
                str(self.state),
                "doctor",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(missing.returncode, 4)
        self.assertEqual(json.loads(missing.stderr)["error"]["code"], "PATH_MISSING")

        locked = self.run_bridge("doctor", env={"FAKE_CLI_MODE": "locked"})
        self.assertEqual(locked.returncode, 4)
        self.assertEqual(self.parsed(locked)["error"]["code"], "STATE_LOCKED")

        schema = self.cli.parent / "schemas/prepare-launch.response.schema.json"
        value = json.loads(schema.read_text(encoding="utf-8"))
        value["$id"] = value["$id"].replace("1.0", "2.0")
        schema.write_text(json.dumps(value), encoding="utf-8")
        incompatible = self.run_bridge("doctor")
        self.assertEqual(incompatible.returncode, 4)
        self.assertEqual(self.parsed(incompatible)["error"]["code"], "SCHEMA_INCOMPATIBLE")

    def test_verbatim_envelope_transport_and_no_mutation_without_receipt(self):
        original = "SYNTHETIC_EPHEMERAL_PROMPT_Ω\nsecond line"
        prepared, ticket = self.prepare(prompt=original)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        result = self.parsed(prepared)["result"]
        self.assertTrue(result["prompt"].startswith(original + "\n\n<orchestrator_launch_envelope>"))
        tool = SyntheticTaskTool()
        external_id = tool.create(prompt=result["prompt"], idempotency_key=result["outbox"]["outbox_id"])
        self.assertEqual(tool.calls[0]["prompt"], result["prompt"])

        denied = self.run_bridge(
            "heartbeat",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            "thread-synthetic",
            "--request-id",
            "heartbeat-denied",
            "--lease-expires-at",
            iso(minutes=40),
            "--now",
            iso(minutes=1),
        )
        self.assertEqual(denied.returncode, 2)
        self.assertEqual(self.parsed(denied)["error"]["code"], "RECEIPT_MISSING")

        receipt = self.receipt(ticket, external_id=external_id)
        self.assertEqual(receipt.returncode, 0, receipt.stderr)
        heartbeat = self.run_bridge(
            "heartbeat",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            external_id,
            "--request-id",
            "heartbeat-ok",
            "--lease-expires-at",
            iso(minutes=40),
            "--now",
            iso(minutes=2),
        )
        self.assertEqual(heartbeat.returncode, 0, heartbeat.stderr)

    def test_stale_fabricated_and_interface_mismatch_fail_closed(self):
        prepared, ticket = self.prepare()
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        stale = self.receipt(ticket, now=iso(minutes=6))
        self.assertEqual(stale.returncode, 2)
        self.assertEqual(self.parsed(stale)["error"]["code"], "RECEIPT_STALE")

        ticket_value = json.loads(ticket.read_text(encoding="utf-8"))
        ticket_value["fencing_token"] = 999
        ticket.write_text(json.dumps(ticket_value), encoding="utf-8")
        fabricated = self.receipt(ticket)
        self.assertEqual(fabricated.returncode, 2)
        self.assertEqual(self.parsed(fabricated)["error"]["code"], "RECEIPT_MISMATCH")

        mismatch = self.run_bridge("doctor", env={"FAKE_CLI_MODE": "bad-interface"})
        self.assertEqual(mismatch.returncode, 4)
        self.assertEqual(self.parsed(mismatch)["error"]["code"], "INTERFACE_INCOMPATIBLE")

    def test_launch_attestation_denies_unattested_api_key_and_model_drift(self):
        prepared, ticket = self.prepare(task_id="runtime-policy")
        self.assertEqual(prepared.returncode, 0, prepared.stderr)

        cases = [
            (
                {
                    **config_verified_runtime_attestation(),
                    "service_tier_attestation": "unattested",
                    "tier_provenance": "none",
                },
                "SERVICE_TIER_UNATTESTED",
            ),
            (
                {
                    **config_verified_runtime_attestation(),
                    "auth_mode": "api-key",
                },
                "FAST_AUTH_MODE_UNSUPPORTED",
            ),
            (
                {
                    **config_verified_runtime_attestation(),
                    "root_model": "gpt-5.6-terra",
                },
                "RUNTIME_ATTESTATION_INVALID",
            ),
        ]
        for value, code in cases:
            with self.subTest(code=code):
                write_json(self.runtime_attestation, value)
                denied = self.receipt(ticket)
                self.assertEqual(2, denied.returncode)
                self.assertEqual(code, self.parsed(denied)["error"]["code"])

        write_json(
            self.runtime_attestation,
            config_verified_runtime_attestation(),
        )
        accepted = self.receipt(ticket)
        self.assertEqual(0, accepted.returncode, accepted.stderr)

    def test_legacy_ticket_migrates_to_13_on_safe_mutation(self):
        prepared, ticket = self.prepare(task_id="ticket-migration")
        self.assertEqual(0, prepared.returncode, prepared.stderr)
        value = json.loads(ticket.read_text(encoding="utf-8"))
        value["ticket_version"] = "1.0"
        value.pop("control_schema_version")
        value.pop("duration_estimate")
        value.pop("owner_claim_id")
        value.pop("runtime_policy")
        ticket.write_text(json.dumps(value), encoding="utf-8")
        migrated = self.receipt(ticket, external_id="ticket-migration-thread")
        self.assertEqual(0, migrated.returncode, migrated.stderr)
        stored = json.loads(ticket.read_text(encoding="utf-8"))
        self.assertEqual("1.3", stored["ticket_version"])
        self.assertEqual("1.0", stored["control_schema_version"])
        self.assertIsNone(stored["duration_estimate"])
        self.assertEqual(
            "gpt-5.6-sol",
            stored["runtime_policy"]["root_model"],
        )

    def test_external_mirror_is_stopped_zero_change_and_excluded_from_capacity(self):
        prepared, ticket = self.prepare(
            task_id="faq-task",
            prompt="SYNTHETIC FAQ DELEGATION",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        canonical_id = "019fabce-d109-canonical"
        receipted = self.receipt(ticket, external_id=canonical_id)
        self.assertEqual(receipted.returncode, 0, receipted.stderr)
        tool = SyntheticTaskTool()
        mirror_id = tool.surface_mirror(
            external_id="019fabce-d77d-mirror",
            prompt=self.parsed(prepared)["result"]["prompt"],
        )
        stopped = self.run_bridge(
            "reconcile-external-task",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            mirror_id,
            "--request-id",
            "faq-live-mirror-race",
            "--now",
            iso(minutes=2),
        )
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        result = self.parsed(stopped)["result"]
        self.assertEqual("DUPLICATE_STOP", result["classification"])
        self.assertEqual(canonical_id, result["canonical_external_thread_id"])
        self.assertFalse(result["mutation_allowed"])
        self.assertFalse(result["capacity_eligible"])
        self.assertEqual(0, result["zero_change_handback"]["changes"])
        tool.stop_zero_change_archive(
            external_id=mirror_id,
            required_actions=result["required_actions"],
        )
        self.assertEqual("archived", tool.mirrors[mirror_id]["state"])
        self.assertEqual(0, tool.mirrors[mirror_id]["changes"])
        canonical = self.run_bridge(
            "reconcile-external-task",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            canonical_id,
            "--request-id",
            "faq-canonical-confirm",
            "--now",
            iso(minutes=2),
        )
        self.assertEqual(canonical.returncode, 0, canonical.stderr)
        self.assertTrue(self.parsed(canonical)["result"]["mutation_allowed"])
        critic_mirror = self.run_bridge(
            "reconcile-external-task",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            "019fabe7-4cba-mirror",
            "--request-id",
            "critic-live-mirror-race",
            "--now",
            iso(minutes=2),
        )
        self.assertEqual(critic_mirror.returncode, 0, critic_mirror.stderr)
        self.assertEqual(
            "DUPLICATE_STOP",
            self.parsed(critic_mirror)["result"]["classification"],
        )

        mirror_heartbeat = self.run_bridge(
            "heartbeat",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            "019fabe7-4cba-mirror",
            "--request-id",
            "mirror-heartbeat",
            "--lease-expires-at",
            iso(minutes=40),
            "--now",
            iso(minutes=2),
        )
        self.assertEqual(3, mirror_heartbeat.returncode)
        self.assertEqual(
            "EXTERNAL_MIRROR_STOP",
            self.parsed(mirror_heartbeat)["error"]["code"],
        )
        mirror_handback = self.run_bridge(
            "record-handback",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            "019fabe7-4cba-mirror",
            "--request",
            str(write_json(self.root / "mirror-handback.json", handback_request())),
        )
        self.assertEqual(3, mirror_handback.returncode)
        self.assertEqual(
            "EXTERNAL_MIRROR_STOP",
            self.parsed(mirror_handback)["error"]["code"],
        )

    def test_decision_routing_denies_unknown_and_catches_owner_downgrade(self):
        routine_path = write_json(self.root / "routine.json", classify_request())
        routine = self.run_bridge("classify-decision", "--request", str(routine_path))
        self.assertEqual(routine.returncode, 0, routine.stderr)
        self.assertEqual(self.parsed(routine)["result"]["classification"], "PM_PROXY")
        self.assertFalse(self.parsed(routine)["result"]["owner_prompt_required"])

        unknown_request = classify_request(action_type="UNRECOGNIZED_ACTION", request_id="unknown")
        unknown_path = write_json(self.root / "unknown.json", unknown_request)
        unknown = self.run_bridge("classify-decision", "--request", str(unknown_path))
        self.assertEqual(unknown.returncode, 2)
        self.assertEqual(self.parsed(unknown)["error"]["code"], "DECISION_DENIED")

        gate_path = write_json(
            self.root / "gate.json",
            classify_request(
                action_type="PRODUCTION_CHANGE",
                gate_type="PRODUCTION_CHANGE",
                request_id="gate",
            ),
        )
        downgrade = self.run_bridge(
            "classify-decision",
            "--request",
            str(gate_path),
            env={"FAKE_CLI_MODE": "owner-downgrade"},
        )
        self.assertEqual(downgrade.returncode, 2)
        self.assertEqual(self.parsed(downgrade)["error"]["code"], "OWNER_GATE_DOWNGRADE")

    def test_policy_privacy_arbitrary_execution_and_conflict_quarantine(self):
        unsafe = policy_rule_request()
        unsafe["rule"]["directive"]["args"] = {"command": "echo forbidden"}
        unsafe_path = write_json(self.root / "unsafe-policy.json", unsafe)
        rejected = self.run_bridge("record-policy-rule", "--request", str(unsafe_path))
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(self.parsed(rejected)["error"]["code"], "ARBITRARY_EXECUTION_DENIED")

        secret = policy_rule_request()
        secret["rule"]["provenance"]["redacted_summary"] = "password=hunter2"
        secret_path = write_json(self.root / "secret-policy.json", secret)
        secret_result = self.run_bridge("record-policy-rule", "--request", str(secret_path))
        self.assertEqual(secret_result.returncode, 2)
        self.assertEqual(self.parsed(secret_result)["error"]["code"], "PRIVACY_DENIED")

        conflict_path = write_json(self.root / "conflict.json", policy_rule_request(rule_id="R-CONFLICT"))
        conflict = self.run_bridge("record-policy-rule", "--request", str(conflict_path))
        self.assertEqual(conflict.returncode, 3)
        self.assertEqual(self.parsed(conflict)["error"]["code"], "POLICY_CONFLICT")
        quarantined = self.run_bridge("doctor")
        self.assertEqual(quarantined.returncode, 3)
        self.assertEqual(self.parsed(quarantined)["error"]["code"], "POLICY_CONFLICT_QUARANTINED")

    def test_durable_state_and_ticket_exclude_prompt_hash_and_private_marker(self):
        marker = "SYNTHETIC_PRIVATE_PROMPT_MARKER_7719"
        prepared, ticket = self.prepare(prompt=marker)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        digest = hashlib.sha256(marker.encode()).hexdigest()
        durable = (self.state / "fake-state.json").read_text(encoding="utf-8")
        ticket_text = ticket.read_text(encoding="utf-8")
        self.assertNotIn(marker, durable)
        self.assertNotIn(marker, ticket_text)
        self.assertNotIn(digest, durable)
        self.assertNotIn(digest, ticket_text)
        self.assertNotIn("prompt_hash", durable)
        self.assertNotIn("prompt_hash", ticket_text)

    def test_handback_requires_receipt_and_records_cleanup(self):
        prepared, ticket = self.prepare()
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        handback_path = write_json(self.root / "handback.json", handback_request())
        denied = self.run_bridge(
            "record-handback",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            "thread-synthetic",
            "--request",
            str(handback_path),
        )
        self.assertEqual(denied.returncode, 2)
        self.assertEqual(self.parsed(denied)["error"]["code"], "RECEIPT_MISSING")
        self.assertEqual(self.receipt(ticket).returncode, 0)
        accepted = self.run_bridge(
            "record-handback",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            "thread-synthetic",
            "--request",
            str(handback_path),
        )
        self.assertEqual(accepted.returncode, 2, accepted.stderr)
        self.assertEqual(
            self.parsed(accepted)["error"]["code"],
            "CLOSURE_SAGA_REQUIRED",
        )


if __name__ == "__main__":
    unittest.main()
