from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests.support import BRIDGE, iso, launch_request, private_temp, recycle_request, write_json


class PinnedFirestarterIntegrationTest(unittest.TestCase):
    def test_exact_pinned_cli_prepare_receipt_heartbeat_and_privacy(self):
        cli_value = os.environ.get("FIRESTARTER_PINNED_CLI")
        repo_value = os.environ.get("FIRESTARTER_PINNED_REPO")
        if not cli_value or not repo_value:
            self.skipTest("set FIRESTARTER_PINNED_CLI and FIRESTARTER_PINNED_REPO")
        cli = Path(cli_value).resolve()
        repo = Path(repo_value).resolve()
        root = private_temp("pm-proxy-pinned-")
        state = root / "state"
        state.mkdir(mode=0o700)

        def run(*args: str):
            return subprocess.run(
                [
                    sys.executable,
                    str(BRIDGE),
                    "--cli",
                    str(cli),
                    "--state-dir",
                    str(state),
                    *args,
                ],
                text=True,
                capture_output=True,
                check=False,
            )

        initialized = run("init", "--now", iso())
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        marker = "SYNTHETIC_PINNED_EPHEMERAL_MARKER_8821"
        recycle = write_json(root / "recycle.json", recycle_request())
        launch_value = launch_request(
            prompt=marker,
            repo_root=str(repo),
            remote="https://github.com/pulkitsinghal/project-firestarter.git",
        )
        launch_value["target"]["base_sha"] = "ac60826b4dbb8622f56732538f44edfecb690eac"
        launch_value["context"]["repo"] = "github.com/pulkitsinghal/project-firestarter"
        launch = write_json(root / "launch.json", launch_value)
        ticket = state / "pinned.ticket.json"
        prepared = run(
            "prepare-launch",
            "--recycle-request",
            str(recycle),
            "--launch-request",
            str(launch),
            "--ticket",
            str(ticket),
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        result = json.loads(prepared.stdout)["result"]
        self.assertTrue(result["prompt"].startswith(marker))
        self.assertIn("BR-LAUNCH-001", result["applicable_rule_ids"])
        self.assertIn("BR-OWNER-001", result["applicable_rule_ids"])
        self.assertGreaterEqual(result["fencing_token"], 1)

        receipt = run(
            "record-launch-receipt",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            "synthetic-pinned-thread",
            "--request-id",
            "pinned-receipt",
            "--now",
            iso(minutes=1),
        )
        self.assertEqual(receipt.returncode, 0, receipt.stderr)
        heartbeat = run(
            "heartbeat",
            "--ticket",
            str(ticket),
            "--external-thread-id",
            "synthetic-pinned-thread",
            "--request-id",
            "pinned-heartbeat",
            "--lease-expires-at",
            iso(minutes=45),
            "--now",
            iso(minutes=2),
        )
        self.assertEqual(heartbeat.returncode, 0, heartbeat.stderr)

        durable = b"".join(
            path.read_bytes()
            for path in state.iterdir()
            if path.is_file()
        )
        self.assertNotIn(marker.encode(), durable)
        self.assertNotIn(hashlib.sha256(marker.encode()).hexdigest().encode(), durable)
        self.assertNotIn(b"prompt_hash", durable)


if __name__ == "__main__":
    unittest.main()
