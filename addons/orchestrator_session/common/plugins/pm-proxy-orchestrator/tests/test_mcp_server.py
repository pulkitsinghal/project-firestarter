from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import unittest
from contextlib import closing
from pathlib import Path

from tests.support import (
    BRIDGE,
    classify_request,
    config_verified_runtime_attestation,
    handback_request,
    iso,
    launch_request,
    private_temp,
    recycle_request,
    refill_request,
)


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER = PLUGIN_ROOT / "scripts" / "mcp_server.py"
PIN_RUNTIME = PLUGIN_ROOT / "scripts" / "configure_runtime_pin.py"


class McpServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = private_temp("pm-proxy-mcp-")
        self.home = self.root / "home"
        self.home.mkdir(mode=0o700)
        self.project = PLUGIN_ROOT.parents[4]
        self.target = self.root / "target-repo"
        self.target.mkdir()
        (self.target / ".git").mkdir()
        (self.target / ".git" / "config").write_text(
            '[remote "origin"]\n'
            "    url = https://github.com/example/project.git\n",
            encoding="utf-8",
        )
        self.cli = (
            self.project
            / "addons"
            / "orchestrator_session"
            / "common"
            / "orchestrator-control"
            / "orchestrator_control.py"
        )
        state_root = self.home / ".codex" / "orchestrator-state"
        state_root.mkdir(parents=True, mode=0o700)
        self.state = state_root / "session"
        self.state.mkdir(mode=0o700)
        self.env = dict(os.environ)
        self.env["HOME"] = str(self.home)
        initialized = subprocess.run(
            [
                sys.executable,
                str(BRIDGE),
                "--cli",
                str(self.cli),
                "--state-dir",
                str(self.state),
                "init",
                "--now",
                iso(),
            ],
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(0, initialized.returncode, initialized.stderr)
        pinned = subprocess.run(
            [
                sys.executable,
                str(PIN_RUNTIME),
                "--project-root",
                str(self.project),
                "--now",
                iso(),
            ],
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(0, pinned.returncode, pinned.stderr)
        self.pin_path = state_root / "runtime-pin.json"
        self.assertEqual(0o600, self.pin_path.stat().st_mode & 0o777)
        self.process = subprocess.Popen(
            [sys.executable, str(SERVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.env,
        )

    def tearDown(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        self.process.terminate()
        self.process.wait(timeout=5)
        if self.process.stdout:
            self.process.stdout.close()
        if self.process.stderr:
            self.process.stderr.close()

    def call(self, name: str, arguments: dict, *, include_meta: bool = False) -> dict:
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": name,
                    "method": "tools/call",
                    "params": {
                        "name": name,
                        "arguments": arguments,
                        **({"_meta": {"progressToken": "synthetic"}} if include_meta else {}),
                    },
                }
            )
            + "\n"
        )
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())

    def common(self) -> dict[str, str]:
        return {
            "project_root": str(self.project),
            "state_dir": str(self.state),
        }

    def adopt_current_plugin(self, request_id: str) -> None:
        plugin_version = json.loads(
            (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )["version"]
        self.record_owner_adoption(
            {
                "interface_version": "1.0",
                "request_id": request_id,
                "adoption_mode": "COVERED_PATH_GUARDRAIL",
                "plugin_version": plugin_version,
                "proofs": {
                    "pre_tool_denial_verified": True,
                    "typed_mcp_control_verified": True,
                    "reserved_create_admission_verified": True,
                    "lifecycle_debt_clear_verified": True,
                    "archive_refill_fence_verified": True,
                    "no_side_effect_canary_verified": True,
                    "hosted_paths_uncovered": True,
                    "universal_coverage_claimed": False,
                },
                "now": iso(),
            }
        )

    def prepare_receipted_task(
        self,
        *,
        ticket_id: str,
        task_id: str,
        fence: int,
        path: str = "/",
    ) -> dict:
        with closing(
            sqlite3.connect(self.state / "orchestrator.sqlite3")
        ) as connection, connection:
            connection.execute("UPDATE metadata SET value=? WHERE key='next_fence'", (str(fence),))
        launch = launch_request(
            task_id=task_id,
            source_event_key=ticket_id,
            outcome_key=f"outcome-{task_id}",
            idempotency_key=f"idem-{task_id}",
            repo_root=str(self.target),
            remote="https://github.com/example/project.git",
        )
        launch["target"]["path"] = path
        launch["target"]["resource_mode"] = "repo-wide" if path == "/" else "path"
        launch["context"]["repo"] = "github.com/example/project"
        launch["context"]["path"] = path
        prepared = self.call(
            "pm_proxy_prepare_launch",
            {
                **self.common(),
                "ticket_id": ticket_id,
                "recycle_request": recycle_request(request_id=f"recycle-{task_id}"),
                "launch_request": launch,
            },
        )["result"]
        self.assertIsNot(prepared.get("isError"), True, prepared)
        receipted = self.call(
            "pm_proxy_record_launch_receipt",
            {
                **self.common(),
                "ticket_id": ticket_id,
                "external_thread_id": f"thread-{task_id}",
                "runtime_attestation": config_verified_runtime_attestation(),
                "request_id": f"receipt-{task_id}",
                "now": iso(minutes=1),
            },
        )["result"]
        self.assertIsNot(receipted.get("isError"), True, receipted)
        ticket = json.loads(
            (self.state / f"{ticket_id}.ticket.json").read_text(encoding="utf-8")
        )
        self.assertEqual(fence, ticket["fencing_token"])
        return ticket

    def set_expired_terminal_evidence(
        self,
        *,
        task_id: str,
        worker_status: str,
        signal: str,
    ) -> None:
        with closing(
            sqlite3.connect(self.state / "orchestrator.sqlite3")
        ) as connection, connection:
            connection.execute(
                """INSERT OR REPLACE INTO lifecycle_watchdog(
                   task_id,lifecycle_state,worker_status,completion_signals_json,
                   evidence_refs_json,remaining_work_json,progress_ref,
                   progress_observed_at,handback_deadline_checks,
                   handback_deadline_limit,required_action,interrupt_receipt_id,
                   updated_at
                ) VALUES(?,'INTERRUPT_REQUIRED',?,?,?,NULL,?,?,2,2,
                         'TERMINALIZE',NULL,?)""",
                (
                    task_id,
                    worker_status,
                    json.dumps([signal]),
                    json.dumps([f"evidence:{task_id}"]),
                    f"progress:{task_id}",
                    iso(minutes=20),
                    iso(minutes=20),
                ),
            )
            connection.execute(
                "UPDATE owner_claims SET expires_at=? WHERE task_id=?",
                (iso(minutes=30), task_id),
            )

    def record_owner_adoption(self, request: dict) -> dict:
        request_path = self.state / ".owner-dispatcher-adoption.json"
        descriptor = os.open(
            request_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                json.dump(request, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(BRIDGE),
                    "--cli",
                    str(self.cli),
                    "--state-dir",
                    str(self.state),
                    "record-dispatcher-adoption",
                    "--request",
                    str(request_path),
                ],
                text=True,
                capture_output=True,
                env=self.env,
                check=False,
            )
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            request_path.unlink(missing_ok=True)
        self.assertEqual(0, completed.returncode, completed.stderr)
        return json.loads(completed.stdout)

    def test_doctor_and_prepare_launch_use_typed_private_surface(self) -> None:
        doctor = self.call(
            "pm_proxy_doctor",
            {"state_dir": str(self.state)},
            include_meta=True,
        )
        tool_result = doctor["result"]
        self.assertIsNot(tool_result.get("isError"), True)
        self.assertEqual("1.4", tool_result["structuredContent"]["result"]["schema_version"])
        pin = tool_result["structuredContent"]["result"]["runtime_pin"]
        self.assertTrue(pin["configured"])
        self.assertTrue(pin["verified"])
        status = self.call("pm_proxy_status", self.common())
        self.assertIsNot(status["result"].get("isError"), True, status)
        plugin_version = json.loads(
            (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )["version"]
        adoption_request = {
            "interface_version": "1.0",
            "request_id": "mcp-adoption",
            "adoption_mode": "COVERED_PATH_GUARDRAIL",
            "plugin_version": plugin_version,
            "proofs": {
                "pre_tool_denial_verified": True,
                "typed_mcp_control_verified": True,
                "reserved_create_admission_verified": True,
                "lifecycle_debt_clear_verified": True,
                "archive_refill_fence_verified": True,
                "no_side_effect_canary_verified": True,
                "hosted_paths_uncovered": True,
                "universal_coverage_claimed": False,
            },
            "now": iso(),
        }
        self.record_owner_adoption(adoption_request)
        current = self.call("pm_proxy_status", self.common())
        lifecycle = current["result"]["structuredContent"]["result"][
            "lifecycle_watchdog"
        ]
        self.assertTrue(lifecycle["covered_path_dispatcher_enforcement"])
        self.assertFalse(lifecycle["platform_dispatcher_enforcement"])
        safety = current["result"]["structuredContent"]["result"][
            "operational_safety"
        ]
        self.assertTrue(safety["runtime_pin_verified"])
        self.assertTrue(safety["automatic_launch_refill_allowed"])
        self.assertTrue(safety["covered_path_automatic_launch_refill_allowed"])
        self.assertFalse(safety["unattended_automatic_launch_refill_allowed"])
        self.assertEqual("COVERED_PATH_ONLY", safety["automatic_launch_refill_scope"])
        self.assertFalse(safety["universal_dispatcher_enforcement"])

        launch = launch_request(task_id="avatar-rig")
        launch["target"]["repo_root"] = str(self.target)
        launch["target"]["remote"] = "https://github.com/example/project.git"
        launch["context"]["repo"] = "github.com/example/project"
        prepared = self.call(
            "pm_proxy_prepare_launch",
            {
                **self.common(),
                "ticket_id": "avatar-rig",
                "recycle_request": recycle_request(request_id="mcp-recycle"),
                "launch_request": launch,
            },
        )
        value = prepared["result"]
        self.assertIsNot(value.get("isError"), True, value)
        payload = value["structuredContent"]
        self.assertTrue(payload["ok"])
        self.assertEqual("avatar-rig", payload["result"]["task_id"])
        self.assertTrue((self.state / "avatar-rig.ticket.json").is_file())
        self.assertFalse(list((self.state / ".mcp-requests").glob("*.json")))

        receipted = self.call(
            "pm_proxy_record_launch_receipt",
            {
                **self.common(),
                "ticket_id": "avatar-rig",
                "external_thread_id": "thread-avatar-rig",
                "runtime_attestation": config_verified_runtime_attestation(),
                "request_id": "receipt-avatar-rig",
                "now": iso(minutes=1),
            },
        )
        self.assertIsNot(receipted["result"].get("isError"), True, receipted)
        ticket = self.state / "avatar-rig.ticket.json"
        original_ticket = ticket.read_bytes()
        retired = self.call(
            "pm_proxy_reconcile_expired_lease",
            {
                **self.common(),
                "ticket_id": "avatar-rig",
                "request_id": "expire-avatar-rig",
                "now": iso(minutes=31),
            },
        )
        self.assertIsNot(retired["result"].get("isError"), True, retired)
        retirement = retired["result"]["structuredContent"]["result"]
        self.assertEqual("EXPIRED", retirement["state"])
        self.assertTrue(retirement["capacity_released"])
        self.assertFalse(retirement["closure_created"])
        self.assertFalse(retirement["archive_created"])
        self.assertFalse(retirement["refill_created"])
        self.assertEqual(original_ticket, ticket.read_bytes())

        evaluated = self.call(
            "pm_proxy_status", {**self.common(), "now": iso(minutes=31)}
        )
        status_value = evaluated["result"]["structuredContent"]["result"]
        self.assertEqual(0, status_value["worker_capacity"]["active_or_reserved_count"])
        expired_task = next(
            item for item in status_value["tasks"] if item["task_id"] == "avatar-rig"
        )
        self.assertEqual("EXPIRED", expired_task["freshness"]["state"])

    def test_setup_failure_and_owner_decision_mcp_routes_are_exact_and_replayable(self) -> None:
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "list-new-tools",
                    "method": "tools/list",
                    "params": {},
                }
            )
            + "\n"
        )
        self.process.stdin.flush()
        discovered = json.loads(self.process.stdout.readline())
        names = {item["name"] for item in discovered["result"]["tools"]}
        self.assertTrue(
            {
                "pm_proxy_acknowledge_control_schema_hold",
                "pm_proxy_record_setup_failure",
                "pm_proxy_route_owner_decision",
            }.issubset(names)
        )
        plugin_version = json.loads(
            (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )["version"]
        self.record_owner_adoption(
            {
                "interface_version": "1.0",
                "request_id": "repair-route-adoption",
                "adoption_mode": "COVERED_PATH_GUARDRAIL",
                "plugin_version": plugin_version,
                "proofs": {
                    "pre_tool_denial_verified": True,
                    "typed_mcp_control_verified": True,
                    "reserved_create_admission_verified": True,
                    "lifecycle_debt_clear_verified": True,
                    "archive_refill_fence_verified": True,
                    "no_side_effect_canary_verified": True,
                    "hosted_paths_uncovered": True,
                    "universal_coverage_claimed": False,
                },
                "now": iso(),
            }
        )
        failed_launch = launch_request(
            task_id="refill-screen-sanitizer-red-team-012",
            source_event_key="source-refill-screen-sanitizer-red-team-012",
            outcome_key="outcome-refill-screen-sanitizer-red-team-012",
            idempotency_key="idem-refill-screen-sanitizer-red-team-012",
        )
        failed_launch["priority"] = 940
        failed_launch["target"]["repo_root"] = str(self.target)
        failed_launch["target"]["remote"] = "https://github.com/example/project.git"
        failed_launch["target"]["path"] = "/docs"
        failed_launch["target"]["resource_mode"] = "path"
        failed_launch["context"]["repo"] = "github.com/example/project"
        failed_launch["context"]["path"] = "/docs"
        prepared = self.call(
            "pm_proxy_prepare_launch",
            {
                **self.common(),
                "ticket_id": "refill-screen-sanitizer-red-team-012",
                "recycle_request": recycle_request(request_id="recycle-p940-012"),
                "launch_request": failed_launch,
            },
        )["result"]
        self.assertIsNot(prepared.get("isError"), True, prepared)
        setup_request = {
            "interface_version": "1.0",
            "request_id": "setup-failure-p940-012",
            "reason_code": "CREATE_THREAD_FAILED",
            "evidence_refs": ["synthetic-expired-unreceipted-p940"],
            "configured_capacity": 4,
            "runnable_queue_count": 0,
            "empty_outcome": "EMPTY",
            "blocked_audits": [],
            "successor_candidates": [],
            "now": iso(minutes=31),
        }
        failed = self.call(
            "pm_proxy_record_setup_failure",
            {
                **self.common(),
                "ticket_id": "refill-screen-sanitizer-red-team-012",
                "request": setup_request,
            },
        )["result"]
        self.assertIsNot(failed.get("isError"), True, failed)
        failure = failed["structuredContent"]["result"]
        self.assertEqual("FAILED", failure["state"])
        self.assertEqual(1, failure["released_claim_count"])
        self.assertEqual(1, failure["poisoned_outbox_count"])
        self.assertIsNone(failure["successor"])
        self.assertFalse(
            (self.state / "screen-sanitizer-red-team-021.ticket.json").exists()
        )
        replay_request = json.loads(json.dumps(setup_request))
        replay_request["now"] = iso(minutes=32)
        replay = self.call(
            "pm_proxy_record_setup_failure",
            {
                **self.common(),
                "ticket_id": "refill-screen-sanitizer-red-team-012",
                "request": replay_request,
            },
        )["result"]
        self.assertIsNot(replay.get("isError"), True, replay)
        self.assertEqual(failure, replay["structuredContent"]["result"])

        routed_launch = launch_request(task_id="screenbench-owner-route")
        routed_launch["target"]["repo_root"] = str(self.target)
        routed_launch["target"]["remote"] = "https://github.com/example/project.git"
        routed_launch["target"]["path"] = "/src"
        routed_launch["target"]["resource_mode"] = "path"
        routed_launch["context"]["repo"] = "github.com/example/project"
        routed_launch["context"]["path"] = "/src"
        routed = self.call(
            "pm_proxy_prepare_launch",
            {
                **self.common(),
                "ticket_id": "screenbench-owner-route",
                "recycle_request": recycle_request(request_id="recycle-screenbench-route"),
                "launch_request": routed_launch,
            },
        )["result"]
        self.assertIsNot(routed.get("isError"), True, routed)
        receipted = self.call(
            "pm_proxy_record_launch_receipt",
            {
                **self.common(),
                "ticket_id": "screenbench-owner-route",
                "external_thread_id": "screenbench-owner-worker",
                "runtime_attestation": config_verified_runtime_attestation(),
                "request_id": "receipt-screenbench-owner-route",
                "now": iso(minutes=2),
            },
        )["result"]
        self.assertIsNot(receipted.get("isError"), True, receipted)
        status = self.call("pm_proxy_status", self.common())["result"][
            "structuredContent"
        ]["result"]
        decision = classify_request(
            action_type="PRODUCTION_CHANGE",
            gate_type="PRODUCTION_CHANGE",
            request_id="screenbench-owner-decision",
        )
        decision["state_revision"] = status["revision"]
        decision["policy_snapshot_revision"] = status["policy_revision"]
        decision["context"]["action"] = "decision-classification"
        decision["now"] = iso(minutes=3)
        route_arguments = {
            **self.common(),
            "ticket_id": "screenbench-owner-route",
            "external_thread_id": "screenbench-owner-worker",
            "route_request_id": "route-screenbench-owner-decision",
            "decision_request": decision,
            "approval": {
                "request_id": "screenbench-owner-decision",
                "decision_code": "production-gate",
                "option_codes": ["approve", "deny"],
                "evidence_refs": ["receipt-screenbench-owner-route"],
            },
            "now": iso(minutes=3),
        }
        first_route = self.call(
            "pm_proxy_route_owner_decision", route_arguments
        )["result"]
        self.assertIsNot(first_route.get("isError"), True, first_route)
        route = first_route["structuredContent"]["result"]
        self.assertEqual("OWNER_GATE", route["classification"])
        self.assertFalse(route["replayed"])
        self.assertIn("<pm_proxy_owner_decision_envelope>", route["message"])
        replayed_route = self.call(
            "pm_proxy_route_owner_decision", route_arguments
        )["result"]
        self.assertTrue(replayed_route["structuredContent"]["result"]["replayed"])
        conflicting_arguments = json.loads(json.dumps(route_arguments))
        conflicting_arguments["route_request_id"] = (
            "route-screenbench-owner-decision-conflict"
        )
        conflicted_route = self.call(
            "pm_proxy_route_owner_decision", conflicting_arguments
        )["result"]
        self.assertTrue(conflicted_route["isError"])
        self.assertEqual(
            "owner-decision-route-conflict",
            conflicted_route["structuredContent"]["error"]["code"],
        )
        ledger_path = self.state / ".owner-decision-routes.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(1, len(ledger["routes"]))
        serialized = json.dumps(ledger, sort_keys=True).lower()
        for forbidden in (
            "prompt", "command", "secret", "credentials", "patient_text",
            "credential_url",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_screen_sanitizer_fence_41_local_artifact_uses_control_validation(self) -> None:
        self.adopt_current_plugin("screen-sanitizer-fence-41-adoption")
        (self.target / "docs").mkdir()
        relative_path = "docs/screen-sanitizer-report.json"
        artifact_path = self.target / relative_path
        artifact_path.write_text("synthetic sanitized artifact\n", encoding="utf-8")
        after = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        ticket = self.prepare_receipted_task(
            ticket_id="screen-sanitizer-ticket-41",
            task_id="screen-sanitizer-fence-41",
            fence=41,
            path="/docs",
        )
        self.set_expired_terminal_evidence(
            task_id="screen-sanitizer-fence-41",
            worker_status="completed",
            signal="worker-final",
        )
        body = {
            "algorithm": "sha256",
            "entries": [
                {
                    "relative_path": relative_path,
                    "transition": "created",
                    "before_sha256": None,
                    "after_sha256": after,
                }
            ],
        }
        manifest = {
            **body,
            "manifest_sha256": hashlib.sha256(
                (
                    json.dumps(body, sort_keys=True, separators=(",", ":"))
                    + "\n"
                ).encode()
            ).hexdigest(),
            "rollback": {
                "strategy": "restore_base",
                "evidence_ref": "rollback-screen-sanitizer-fence-41",
            },
        }
        handback = handback_request(
            task_id="screen-sanitizer-fence-41",
            handback_id="screen-sanitizer-fence-41",
            now=iso(minutes=32),
        )
        for key in ("policy_snapshot_revision", "lease_epoch", "fencing_token"):
            handback[key] = ticket[key]
        handback.update(
            {
                "disposition": "completed_local_artifact",
                "exact_refs": {
                    "base_sha": "a" * 40,
                    "candidate_sha": None,
                    "pr_url": None,
                    "merge_sha": None,
                    "default_sha": None,
                },
                "external_delivery": "not_performed",
                "artifacts": [relative_path],
                "local_artifact": manifest,
                "resources": [
                    {
                        "id": ticket["owner_claim_id"],
                        "disposition": "removed",
                        "reason": "synthetic owner claim released",
                        "bytes": 0,
                    },
                    {
                        "id": relative_path,
                        "disposition": "retain",
                        "reason": "bounded synthetic local artifact",
                        "bytes": artifact_path.stat().st_size,
                    },
                ],
            }
        )
        refill = refill_request(
            request_id="screen-sanitizer-fence-41",
            capacity=4,
            now=iso(minutes=32),
        )
        invalid = json.loads(json.dumps(handback))
        invalid["local_artifact"]["entries"][0]["after_sha256"] = "f" * 64
        invalid_body = {
            "algorithm": invalid["local_artifact"]["algorithm"],
            "entries": invalid["local_artifact"]["entries"],
        }
        invalid["local_artifact"]["manifest_sha256"] = hashlib.sha256(
            (
                json.dumps(invalid_body, sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode()
        ).hexdigest()
        rejected = self.call(
            "pm_proxy_close_and_refill",
            {
                **self.common(),
                "predecessor_ticket_id": "screen-sanitizer-ticket-41",
                "handback_request": invalid,
                "refill_request": refill,
            },
        )["result"]
        self.assertTrue(rejected["isError"])
        self.assertEqual(
            "artifact-content-mismatch",
            rejected["structuredContent"]["error"]["code"],
        )
        self.assertFalse((self.state / "pm-proxy-refill-ledger.json").exists())

        closed = self.call(
            "pm_proxy_close_and_refill",
            {
                **self.common(),
                "predecessor_ticket_id": "screen-sanitizer-ticket-41",
                "handback_request": handback,
                "refill_request": refill,
            },
        )["result"]
        self.assertIsNot(closed.get("isError"), True, closed)
        result = closed["structuredContent"]["result"]
        self.assertEqual("EMPTY", result["outcome"])
        with closing(
            sqlite3.connect(self.state / "orchestrator.sqlite3")
        ) as connection:
            stored = json.loads(
                connection.execute(
                    "SELECT result_json FROM handbacks WHERE handback_id=?",
                    ("screen-sanitizer-fence-41",),
                ).fetchone()[0]
            )
        self.assertEqual(
            manifest["manifest_sha256"],
            stored["local_artifact_manifest_sha256"],
        )

    def test_screenbench_fence_42_mcp_replays_stale_terminal_evidence_atomically(self) -> None:
        self.adopt_current_plugin("screenbench-fence-42-adoption")
        ticket = self.prepare_receipted_task(
            ticket_id="screenbench-ticket-42",
            task_id="screenbench-fence-42",
            fence=42,
        )
        database = self.state / "orchestrator.sqlite3"
        self.set_expired_terminal_evidence(
            task_id="screenbench-fence-42",
            worker_status="waiting",
            signal="accepted-schema-defect-replay",
        )
        terminal_status = self.call(
            "pm_proxy_status",
            {**self.common(), "now": iso(minutes=32)},
        )["result"]["structuredContent"]["result"]
        terminal_task = next(
            item
            for item in terminal_status["tasks"]
            if item["task_id"] == "screenbench-fence-42"
        )
        self.assertEqual(
            "INTERRUPT_REQUIRED",
            terminal_task["lifecycle"]["lifecycle_state"],
        )
        self.assertEqual("waiting", terminal_task["lifecycle"]["worker_status"])
        self.assertEqual("TERMINALIZE", terminal_task["lifecycle"]["required_action"])
        self.assertIsNone(terminal_task["control_schema_hold"])
        self.assertEqual(
            ticket["owner_claim_id"],
            terminal_task["receipt_fence"]["owner_claim_id"],
        )

        handback = handback_request(
            task_id="screenbench-fence-42",
            handback_id="screenbench-fence-42",
            now=iso(minutes=32),
        )
        for key in ("policy_snapshot_revision", "lease_epoch", "fencing_token"):
            handback[key] = ticket[key]
        handback.update(
            {
                "disposition": "completed_local_only",
                "exact_refs": {
                    "base_sha": "a" * 40,
                    "candidate_sha": "b" * 40,
                    "pr_url": None,
                    "merge_sha": None,
                    "default_sha": None,
                },
                "external_delivery": "not_performed",
                "dependencies": ["accepted-schema-defect-replay"],
                "resources": [
                    {
                        "id": ticket["owner_claim_id"],
                        "disposition": "removed",
                        "reason": "exact synthetic owner claim released",
                        "bytes": 0,
                    }
                ],
            }
        )
        closed = self.call(
            "pm_proxy_close_and_refill",
            {
                **self.common(),
                "predecessor_ticket_id": "screenbench-ticket-42",
                "handback_request": handback,
                "refill_request": refill_request(
                    request_id="screenbench-fence-42",
                    capacity=4,
                    now=iso(minutes=32),
                ),
            },
        )["result"]
        self.assertIsNot(closed.get("isError"), True, closed)
        result = closed["structuredContent"]["result"]
        self.assertEqual("EMPTY", result["outcome"])
        self.assertTrue(result["capacity_released"])
        self.assertEqual([], result["launches"])
        with closing(sqlite3.connect(database)) as connection:
            connection.row_factory = sqlite3.Row
            task = connection.execute(
                "SELECT state FROM tasks WHERE task_id=?",
                ("screenbench-fence-42",),
            ).fetchone()
            claim = connection.execute(
                "SELECT status FROM owner_claims WHERE task_id=?",
                ("screenbench-fence-42",),
            ).fetchone()
            hold_count = connection.execute(
                "SELECT COUNT(*) FROM control_schema_holds WHERE task_id=?",
                ("screenbench-fence-42",),
            ).fetchone()[0]
            handback_count = connection.execute(
                "SELECT COUNT(*) FROM handbacks WHERE handback_id=?",
                ("screenbench-fence-42",),
            ).fetchone()[0]
            archive = connection.execute(
                "SELECT state FROM outbox WHERE task_id=? AND kind='ARCHIVE_THREAD'",
                ("screenbench-fence-42",),
            ).fetchone()
            capacity = connection.execute(
                "SELECT outcome FROM capacity_sagas WHERE saga_id=?",
                ("screenbench-fence-42",),
            ).fetchone()
        self.assertEqual("ARCHIVE_PENDING", task["state"])
        self.assertEqual("released", claim["status"])
        self.assertEqual(0, hold_count)
        self.assertEqual(1, handback_count)
        self.assertEqual("pending", archive["state"])
        self.assertEqual("EMPTY", capacity["outcome"])

    def test_runtime_pin_rejects_mismatch_and_bundle_drift(self) -> None:
        mismatched = self.call(
            "pm_proxy_doctor",
            {
                "project_root": str(self.target),
                "state_dir": str(self.state),
            },
        )["result"]
        self.assertTrue(mismatched["isError"])
        self.assertEqual(
            "runtime-project-root-mismatch",
            mismatched["structuredContent"]["error"]["code"],
        )

        pin = json.loads(self.pin_path.read_text(encoding="utf-8"))
        pin["runtime_sha256"] = "0" * 64
        self.pin_path.write_text(
            json.dumps(pin, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        drifted = self.call(
            "pm_proxy_doctor", {"state_dir": str(self.state)}
        )["result"]
        self.assertTrue(drifted["isError"])
        self.assertEqual(
            "runtime-pin-drift",
            drifted["structuredContent"]["error"]["code"],
        )

    def test_capacity_reconfiguration_requires_covered_root_and_replays_truthfully(
        self,
    ) -> None:
        plugin_version = json.loads(
            (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )["version"]
        self.record_owner_adoption(
            {
                "interface_version": "1.0",
                "request_id": "capacity-adoption",
                "adoption_mode": "COVERED_PATH_GUARDRAIL",
                "plugin_version": plugin_version,
                "proofs": {
                    "pre_tool_denial_verified": True,
                    "typed_mcp_control_verified": True,
                    "reserved_create_admission_verified": True,
                    "lifecycle_debt_clear_verified": True,
                    "archive_refill_fence_verified": True,
                    "no_side_effect_canary_verified": True,
                    "hosted_paths_uncovered": True,
                    "universal_coverage_claimed": False,
                },
                "now": iso(),
            }
        )
        status = self.call("pm_proxy_status", self.common())["result"]
        status_value = status["structuredContent"]["result"]
        request = {
            **self.common(),
            "request_id": "capacity-four-to-eight",
            "expected_state_revision": status_value["revision"],
            "expected_configured_capacity": 4,
            "requested_configured_capacity": 8,
            "evidence_refs": ["owner-request-capacity-eight"],
            "now": iso(minutes=1),
        }
        changed = self.call("pm_proxy_configure_capacity", request)["result"]
        self.assertIsNot(changed.get("isError"), True, changed)
        result = changed["structuredContent"]["result"]
        self.assertEqual(4, result["previous_configured_capacity"])
        self.assertEqual(8, result["configured_capacity"])
        self.assertFalse(result["replayed"])
        self.assertEqual(
            result["previous_state_revision"] + 1,
            result["committed_state_revision"],
        )

        replayed = self.call("pm_proxy_configure_capacity", request)["result"]
        self.assertIsNot(replayed.get("isError"), True, replayed)
        replay = replayed["structuredContent"]["result"]
        self.assertTrue(replay["replayed"])
        self.assertEqual(
            result["committed_state_revision"],
            replay["committed_state_revision"],
        )
        current = self.call("pm_proxy_status", self.common())["result"]
        current_value = current["structuredContent"]["result"]
        self.assertEqual(
            {
                "configured_capacity": 8,
                "active_or_reserved_count": 0,
                "root_excluded": True,
            },
            current_value["worker_capacity"],
        )

        for minute, expected, requested in (
            (2, 8, 6),
            (3, 6, 8),
            (4, 8, 4),
        ):
            before = self.call("pm_proxy_status", self.common())["result"]
            before_value = before["structuredContent"]["result"]
            rollback = self.call(
                "pm_proxy_configure_capacity",
                {
                    **self.common(),
                    "request_id": f"capacity-{expected}-to-{requested}",
                    "expected_state_revision": before_value["revision"],
                    "expected_configured_capacity": expected,
                    "requested_configured_capacity": requested,
                    "evidence_refs": [f"owner-capacity-{expected}-to-{requested}"],
                    "now": iso(minutes=minute),
                },
            )["result"]
            self.assertIsNot(rollback.get("isError"), True, rollback)
            rollback_value = rollback["structuredContent"]["result"]
            self.assertEqual(expected, rollback_value["previous_configured_capacity"])
            self.assertEqual(requested, rollback_value["configured_capacity"])

        final = self.call("pm_proxy_status", self.common())["result"]
        final_value = final["structuredContent"]["result"]
        self.assertEqual(4, final_value["worker_capacity"]["configured_capacity"])
        audit = json.loads(
            (self.state / "root-role-audit.json").read_text(encoding="utf-8")
        )
        capacity_records = [
            record
            for record in audit["records"]
            if record["action_type"] == "configure_capacity"
        ]
        self.assertEqual(5, len(capacity_records))
        self.assertTrue(
            all(record["decision"] == "ALLOW" for record in capacity_records)
        )

    def test_runtime_pin_permissions_fail_closed(self) -> None:
        os.chmod(self.pin_path, 0o644)
        denied = self.call(
            "pm_proxy_doctor", {"state_dir": str(self.state)}
        )["result"]
        self.assertTrue(denied["isError"])
        self.assertEqual(
            "runtime-pin-not-private",
            denied["structuredContent"]["error"]["code"],
        )

    def test_runtime_pin_malformed_json_has_bounded_error(self) -> None:
        self.pin_path.write_text("{\"pin_version\":", encoding="utf-8")
        denied = self.call(
            "pm_proxy_doctor", {"state_dir": str(self.state)}
        )["result"]
        self.assertTrue(denied["isError"])
        self.assertEqual(
            "runtime-pin-invalid",
            denied["structuredContent"]["error"]["code"],
        )

    def test_dispatcher_adoption_is_not_an_mcp_self_approval_tool(self) -> None:
        denied = self.call(
            "pm_proxy_record_dispatcher_adoption",
            {**self.common(), "request": {}},
        )
        self.assertEqual("unknown-tool", denied["error"]["message"])

    def test_unpinned_bootstrap_is_read_only_and_cannot_launch(self) -> None:
        self.pin_path.unlink()
        doctor = self.call("pm_proxy_doctor", self.common())["result"]
        self.assertIsNot(doctor.get("isError"), True, doctor)
        pin = doctor["structuredContent"]["result"]["runtime_pin"]
        self.assertFalse(pin["configured"])
        launch = launch_request(task_id="unpinned")
        launch["target"]["repo_root"] = str(self.target)
        launch["target"]["remote"] = "https://github.com/example/project.git"
        launch["context"]["repo"] = "github.com/example/project"
        denied = self.call(
            "pm_proxy_prepare_launch",
            {
                **self.common(),
                "ticket_id": "unpinned",
                "recycle_request": recycle_request(request_id="unpinned-recycle"),
                "launch_request": launch,
            },
        )["result"]
        self.assertTrue(denied["isError"])
        self.assertEqual(
            "runtime-pin-required",
            denied["structuredContent"]["error"]["code"],
        )
        self.assertFalse((self.state / "unpinned.ticket.json").exists())

    def test_pinned_runtime_still_requires_current_dispatcher_adoption(self) -> None:
        status = self.call("pm_proxy_status", self.common())["result"]
        safety = status["structuredContent"]["result"]["operational_safety"]
        self.assertTrue(safety["runtime_pin_verified"])
        self.assertFalse(safety["automatic_launch_refill_allowed"])
        self.assertFalse(safety["covered_path_automatic_launch_refill_allowed"])
        self.assertFalse(safety["unattended_automatic_launch_refill_allowed"])
        self.assertEqual("DISABLED", safety["automatic_launch_refill_scope"])
        capacity_denied = self.call(
            "pm_proxy_configure_capacity",
            {
                **self.common(),
                "request_id": "unadopted-capacity",
                "expected_state_revision": status["structuredContent"]["result"][
                    "revision"
                ],
                "expected_configured_capacity": 4,
                "requested_configured_capacity": 8,
                "evidence_refs": ["owner-request-capacity-eight"],
                "now": iso(),
            },
        )["result"]
        self.assertTrue(capacity_denied["isError"])
        self.assertEqual(
            "dispatcher-adoption-required",
            capacity_denied["structuredContent"]["error"]["code"],
        )
        launch = launch_request(task_id="unadopted")
        launch["target"]["repo_root"] = str(self.target)
        launch["target"]["remote"] = "https://github.com/example/project.git"
        launch["context"]["repo"] = "github.com/example/project"
        denied = self.call(
            "pm_proxy_prepare_launch",
            {
                **self.common(),
                "ticket_id": "unadopted",
                "recycle_request": recycle_request(request_id="unadopted-recycle"),
                "launch_request": launch,
            },
        )["result"]
        self.assertTrue(denied["isError"])
        self.assertEqual(
            "dispatcher-adoption-required",
            denied["structuredContent"]["error"]["code"],
        )
        self.assertFalse((self.state / "unadopted.ticket.json").exists())
        for name, extra in (
            ("pm_proxy_watchdog_refill", {}),
            (
                "pm_proxy_close_and_refill",
                {
                    "predecessor_ticket_id": "missing-predecessor",
                    "handback_request": {},
                },
            ),
        ):
            blocked = self.call(
                name,
                {
                    **self.common(),
                    "refill_request": refill_request(),
                    **extra,
                },
            )["result"]
            self.assertTrue(blocked["isError"])
            self.assertEqual(
                "dispatcher-adoption-required",
                blocked["structuredContent"]["error"]["code"],
            )

    def test_state_escape_and_unknown_fields_fail_closed(self) -> None:
        outside = self.root / "outside"
        outside.mkdir(mode=0o700)
        escaped = self.call(
            "pm_proxy_doctor",
            {"project_root": str(self.project), "state_dir": str(outside)},
        )["result"]
        self.assertTrue(escaped["isError"])
        self.assertEqual(
            "state-dir-outside-private-root",
            escaped["structuredContent"]["error"]["code"],
        )

        state_alias = self.state.parent / "state-alias"
        state_alias.symlink_to(self.state, target_is_directory=True)
        aliased = self.call(
            "pm_proxy_doctor",
            {"project_root": str(self.project), "state_dir": str(state_alias)},
        )["result"]
        self.assertTrue(aliased["isError"])
        self.assertEqual(
            "state-dir-symlink",
            aliased["structuredContent"]["error"]["code"],
        )

        os.chmod(self.state.parent, 0o755)
        exposed_root = self.call("pm_proxy_doctor", self.common())["result"]
        self.assertTrue(exposed_root["isError"])
        self.assertEqual(
            "state-root-not-private",
            exposed_root["structuredContent"]["error"]["code"],
        )
        os.chmod(self.state.parent, 0o700)

        unknown = self.call(
            "pm_proxy_doctor",
            {**self.common(), "command": "touch /tmp/never"},
        )["result"]
        self.assertTrue(unknown["isError"])
        self.assertEqual("invalid-fields", unknown["structuredContent"]["error"]["code"])


if __name__ == "__main__":
    unittest.main()
