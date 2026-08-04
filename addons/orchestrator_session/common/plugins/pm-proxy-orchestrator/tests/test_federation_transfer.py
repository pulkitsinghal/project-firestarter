from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "scripts" / "federation_transfer.py"
SPEC = importlib.util.spec_from_file_location("federation_transfer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
REPO_ROOT = PLUGIN_ROOT.parents[4]
CLI = (
    REPO_ROOT
    / "addons"
    / "orchestrator_session"
    / "common"
    / "orchestrator-control"
    / "orchestrator_control.py"
)


def private(path: Path) -> Path:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


class FederationTransferTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = tempfile.TemporaryDirectory(prefix="pm-proxy-federation-")
        self.root = private(Path(self.sandbox.name))
        self.target = self.root / "target"
        self.sources = [self.root / "source-a", self.root / "source-b"]
        self.hosts = [self.root / "host-a", self.root / "host-b"]
        for state in [self.target, *self.sources]:
            self.init_state(state)
        for index, host in enumerate(self.hosts):
            self.write_host(host, f"source-host-{index + 1}")

    def tearDown(self) -> None:
        self.sandbox.cleanup()

    @staticmethod
    def init_state(state: Path) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(CLI),
                "--state-dir",
                str(state),
                "init",
                "--now",
                "2026-08-03T18:00:00Z",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)

    @staticmethod
    def write_host(
        host: Path,
        instance_id: str,
        *,
        armed: bool = False,
        desktop_pid: int | None = None,
    ) -> None:
        private(host)
        session = host / "session.json"
        session.write_text(
            json.dumps(
                {
                    "instance_id": instance_id,
                    "armed": armed,
                    "desktop_pid": desktop_pid,
                    "proxy_pid": None,
                    "app_server_pid": None,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        os.chmod(session, 0o600)

    def command(self, operation: str) -> list[str]:
        arguments = [
            sys.executable,
            "-B",
            str(SCRIPT),
            "--cli",
            str(CLI),
            "--target-state",
            str(self.target),
        ]
        for source in self.sources:
            arguments.extend(["--source-state", str(source)])
        for host in self.hosts:
            arguments.extend(["--source-host-dir", str(host)])
        return [
            *arguments,
            "--transfer-id",
            "synthetic-two-orc-transfer",
            "--evidence-ref",
            "synthetic-owner-authorization",
            "--now",
            "2026-08-03T18:10:00Z",
            operation,
        ]

    def test_apply_is_resumable_and_preserves_two_four_lane_shards(self) -> None:
        first = subprocess.run(
            self.command("apply"),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, first.returncode, first.stderr)
        result = json.loads(first.stdout)
        self.assertTrue(result["single_active_root"])
        self.assertEqual("ACTIVE_FEDERATION_ROOT", result["target"]["state"])
        self.assertEqual(8, result["target"]["federated_configured_capacity"])
        self.assertEqual(
            ["SUBORDINATE", "SUBORDINATE"],
            [source["state"] for source in result["sources"]],
        )
        self.assertEqual(
            [4, 4], [source["configured_capacity"] for source in result["sources"]]
        )
        self.assertTrue(
            all(item["processes_absent"] for item in result["source_host_evidence"])
        )

        replay = subprocess.run(
            self.command("apply"),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, replay.returncode, replay.stderr)
        self.assertTrue(json.loads(replay.stdout)["single_active_root"])

    def test_disarmed_host_accepts_historical_dead_pid_and_rejects_live_pid(
        self,
    ) -> None:
        dead_host = self.root / "dead-host"
        self.write_host(dead_host, "dead-host", desktop_pid=2_147_483_647)
        evidence = MODULE.disarmed_host(str(dead_host))
        self.assertTrue(evidence["processes_absent"])

        live_host = self.root / "live-host"
        self.write_host(live_host, "live-host", desktop_pid=os.getpid())
        with self.assertRaisesRegex(
            MODULE.TransferError, "source-host-process-still-running"
        ):
            MODULE.disarmed_host(str(live_host))

    def test_armed_source_host_fails_before_authority_mutation(self) -> None:
        self.write_host(self.hosts[0], "source-host-1", armed=True)
        denied = subprocess.run(
            self.command("apply"),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(4, denied.returncode)
        self.assertEqual(
            "FEDERATION_TRANSFER_FAIL_CLOSED",
            json.loads(denied.stderr)["error"]["code"],
        )
        observed = subprocess.run(
            self.command("status"),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, observed.returncode, observed.stderr)
        status = json.loads(observed.stdout)
        self.assertEqual("ACTIVE_ROOT", status["target"]["state"])
        self.assertEqual(
            ["ACTIVE_ROOT", "ACTIVE_ROOT"],
            [source["state"] for source in status["sources"]],
        )


if __name__ == "__main__":
    unittest.main()
