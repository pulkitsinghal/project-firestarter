from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PLUGIN_ROOT / "scripts" / "mcp_server.py"
SPEC = importlib.util.spec_from_file_location("pm_proxy_bootstrap_server", SERVER_PATH)
assert SPEC and SPEC.loader
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


def private(path: Path) -> Path:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


class BootstrapRecoveryGrantTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="pm-proxy-bootstrap-")
        self.root = private(Path(self.temporary.name).resolve())
        self.project = private(self.root / "project")
        self.source_plugin = private(self.project / "source-plugin")
        self.state = private(self.root / "state")
        self.instance = private(self.root / "instance")
        self.path = self.instance / "bootstrap-recovery-grant-grant-1.json"
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        self.arguments = {
            "project_root": str(self.project),
            "state_dir": str(self.state),
            "request_id": "hold-request-1",
            "authorization_request_id": "owner-authorization-1",
            "decision_request_id": "decision-request-1",
            "decision_id": "decision-1",
            "decision": SERVER.CONTROL_SCHEMA_HOLD_DECISION,
            "root_thread_id": "root-thread-1",
            "ticket_id": "ticket-1",
            "task_id": "task-1",
            "external_thread_id": "worker-thread-1",
            "expected_state_revision": 607,
            "expected_policy_revision": 2,
            "expected_configured_capacity": 5,
            "policy_snapshot_revision": 2,
            "lease_epoch": 1,
            "fencing_token": 38,
            "replay_target": SERVER.CONTROL_SCHEMA_HOLD_REPLAY_TARGET,
            "now": (now - dt.timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        }
        self.grant = {
            "authorization_request_id": self.arguments["authorization_request_id"],
            "base_sha": "a" * 40,
            "configured_capacity": 5,
            "decision": SERVER.CONTROL_SCHEMA_HOLD_DECISION,
            "decision_id": self.arguments["decision_id"],
            "decision_request_id": self.arguments["decision_request_id"],
            "expected_state_revision": 607,
            "expires_at": (now + dt.timedelta(seconds=120)).isoformat().replace("+00:00", "Z"),
            "external_thread_id": self.arguments["external_thread_id"],
            "fencing_token": 38,
            "grant_id": "grant-1",
            "grant_version": SERVER.BOOTSTRAP_GRANT_VERSION,
            "instance_dir": str(self.instance),
            "instance_id": "isolated-host-1",
            "issued_at": self.arguments["now"],
            "lease_epoch": 1,
            "max_uses": 1,
            "operation": "pm_proxy_acknowledge_control_schema_hold",
            "plugin_root": str(self.source_plugin),
            "plugin_tree_sha256": "c" * 64,
            "plugin_version": SERVER.SERVER_VERSION,
            "policy_snapshot_revision": 2,
            "policy_revision": 2,
            "project_root": str(self.project),
            "request_id": self.arguments["request_id"],
            "replay_target": SERVER.CONTROL_SCHEMA_HOLD_REPLAY_TARGET,
            "root_thread_id": self.arguments["root_thread_id"],
            "runtime_sha256": "d" * 64,
            "source_commit_sha": "b" * 40,
            "state_dir": str(self.state),
            "task_id": self.arguments["task_id"],
            "ticket_id": self.arguments["ticket_id"],
        }
        self.grant["binding_sha256"] = SERVER.canonical_sha256(self.grant)
        self.path.write_text(
            json.dumps(self.grant, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.chmod(self.path, 0o600)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exact_grant_is_private_revoked_once_and_finalized(self) -> None:
        consumed = SERVER.consume_bootstrap_grant(self.state, self.path, self.grant)
        self.assertEqual("REVOKED", consumed["status"])
        self.assertTrue(consumed["consumed_before_dispatch"])
        self.assertEqual("DISPATCH_PENDING", consumed["dispatch_status"])
        ledger = self.state / ".bootstrap-recovery-revocations.json"
        self.assertEqual(0o600, ledger.stat().st_mode & 0o777)
        with self.assertRaisesRegex(SERVER.McpError, "bootstrap-grant-revoked"):
            SERVER.consume_bootstrap_grant(self.state, self.path, self.grant)
        final = SERVER.finalize_bootstrap_grant(
            self.state, self.grant, "ACKNOWLEDGED", response_sha256="e" * 64
        )
        self.assertEqual("ACKNOWLEDGED", final["dispatch_status"])
        self.assertEqual(1, final["use_count"])

    def test_concurrent_consumers_allow_exactly_one_use(self) -> None:
        barrier = threading.Barrier(3)

        def attempt() -> str:
            barrier.wait()
            try:
                SERVER.consume_bootstrap_grant(self.state, self.path, self.grant)
                return "consumed"
            except SERVER.McpError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt) for _ in range(2)]
            barrier.wait()
            results = [future.result(timeout=2) for future in futures]
        self.assertCountEqual(["consumed", "bootstrap-grant-revoked"], results)

    def test_control_call_consumes_before_fixed_hold_dispatch(self) -> None:
        ticket = self.state / "ticket-1.ticket.json"
        ticket.write_text("{}\n", encoding="utf-8")
        os.chmod(ticket, 0o600)
        order: list[str] = []

        def consume(_state: Path, _path: Path, _grant: dict) -> dict:
            order.append("consume")
            return {}

        def dispatch(_arguments: list[str], *, timeout: int = 30) -> dict:
            del timeout
            order.append("dispatch")
            return {
                "ok": True,
                "operation": "acknowledge-control-schema-hold",
                "result": {
                    "hold_state": "CONTROL_SCHEMA_HOLD",
                    "required_action": "AWAIT_CONTROL_REPAIR",
                },
            }

        with (
            mock.patch.object(SERVER, "common", return_value=(self.project, self.state)),
            mock.patch.object(SERVER, "bridge_base", return_value=["bridge"]),
            mock.patch.object(SERVER, "require_automatic_control_ready"),
            mock.patch.object(SERVER, "root_guard"),
            mock.patch.object(
                SERVER,
                "validate_bootstrap_grant",
                return_value=(self.path, self.grant),
            ),
            mock.patch.object(SERVER, "consume_bootstrap_grant", side_effect=consume),
            mock.patch.object(SERVER, "invoke", side_effect=dispatch),
            mock.patch.object(
                SERVER,
                "finalize_bootstrap_grant",
                return_value={
                    "consumed_at": "2026-08-04T00:00:00Z",
                    "dispatch_status": "ACKNOWLEDGED",
                },
            ),
        ):
            payload = SERVER.control_call(
                "pm_proxy_acknowledge_control_schema_hold", self.arguments
            )
        self.assertEqual(["consume", "dispatch"], order)
        receipt = payload["result"]["bootstrap_recovery_grant"]
        self.assertEqual("REVOKED", receipt["status"])
        self.assertTrue(receipt["consumed_before_dispatch"])
        self.assertEqual(1, receipt["use_count"])


if __name__ == "__main__":
    unittest.main()
