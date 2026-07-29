from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from tests.support import (
    BRIDGE,
    handback_request,
    iso,
    launch_request,
    make_fake_install,
    private_temp,
    recycle_request,
    write_json,
)


class CrashRecoveryTestCase(unittest.TestCase):
    def setUp(self):
        self.root = private_temp("pm-proxy-crash-")
        self.cli = make_fake_install(self.root)
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)

    def run_bridge(self, *args: str, mode: str | None = None):
        environment = os.environ.copy()
        if mode:
            environment["FAKE_CLI_MODE"] = mode
        return subprocess.run(
            [
                sys.executable,
                str(BRIDGE),
                "--cli",
                str(self.cli),
                "--state-dir",
                str(self.state),
                *args,
            ],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

    def test_terminal_handback_cannot_bypass_atomic_refill_saga(self):
        recycle = write_json(self.root / "recycle.json", recycle_request())
        launch = write_json(self.root / "launch.json", launch_request())
        ticket = self.state / "task.ticket.json"
        prepared = self.run_bridge(
            "prepare-launch",
            "--recycle-request",
            str(recycle),
            "--launch-request",
            str(launch),
            "--ticket",
            str(ticket),
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        receipt = self.run_bridge(
            "record-launch-receipt",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            "thread-1",
            "--request-id",
            "receipt-1",
            "--now",
            iso(minutes=1),
        )
        self.assertEqual(receipt.returncode, 0, receipt.stderr)

        successor = launch_request(
            task_id="task-2",
            source_event_key="source-2",
            outcome_key="outcome-2",
            idempotency_key="idem-2",
            prompt="SYNTHETIC_SUCCESSOR_PROMPT",
            now=iso(minutes=2),
            lease_expires_at=iso(minutes=32),
        )
        handback = write_json(
            self.root / "handback.json",
            handback_request(successor=successor, now=iso(minutes=2)),
        )
        crashed = self.run_bridge(
            "record-handback",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            "thread-1",
            "--request",
            str(handback),
            mode="crash-after-handback-commit",
        )
        self.assertEqual(crashed.returncode, 2)
        self.assertEqual(
            json.loads(crashed.stderr)["error"]["code"],
            "CLOSURE_SAGA_REQUIRED",
        )
        state = json.loads(
            (self.state / "fake-state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(state["tasks"]["task-1"]["state"], "RUNNING")
        self.assertNotIn("task-2", state["tasks"])


if __name__ == "__main__":
    unittest.main()
