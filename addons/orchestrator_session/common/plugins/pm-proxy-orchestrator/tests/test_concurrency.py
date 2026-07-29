from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from tests.support import BRIDGE, launch_request, make_fake_install, private_temp, recycle_request, write_json
from tests.task_tool_stub import SyntheticTaskTool


class ConcurrencyTestCase(unittest.TestCase):
    def test_duplicate_prepare_create_race_has_one_owner_and_one_external_create(self):
        for iteration in range(20):
            root = private_temp(f"pm-proxy-race-{iteration}-")
            cli = make_fake_install(root)
            state = root / "state"
            state.mkdir(mode=0o700)
            commands = []
            for lane in ("a", "b"):
                recycle = write_json(
                    root / f"recycle-{lane}.json",
                    recycle_request(request_id=f"recycle-{iteration}-{lane}"),
                )
                launch = launch_request(
                    task_id=f"task-{iteration}-{lane}",
                    source_event_key=f"shared-source-{iteration}",
                    outcome_key=f"shared-outcome-{iteration}",
                    idempotency_key=f"shared-idem-{iteration}",
                )
                launch_path = write_json(root / f"launch-{lane}.json", launch)
                ticket = state / f"ticket-{lane}.json"
                commands.append(
                    [
                        sys.executable,
                        str(BRIDGE),
                        "--cli",
                        str(cli),
                        "--state-dir",
                        str(state),
                        "prepare-launch",
                        "--recycle-request",
                        str(recycle),
                        "--launch-request",
                        str(launch_path),
                        "--ticket",
                        str(ticket),
                    ]
                )
            environment = os.environ.copy()
            environment["FAKE_PREPARE_DELAY"] = "0.01"
            processes = [
                subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
                for command in commands
            ]
            results = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=10)
                results.append((process.returncode, stdout, stderr))
            self.assertEqual(sorted(code for code, _, _ in results), [0, 3])

            tool = SyntheticTaskTool()
            for code, stdout, _ in results:
                if code == 0:
                    result = json.loads(stdout)["result"]
                    tool.create(prompt=result["prompt"], idempotency_key=result["outbox"]["outbox_id"])
            self.assertEqual(len(tool.calls), 1)
            state_value = json.loads((state / "fake-state.json").read_text(encoding="utf-8"))
            self.assertEqual(len(state_value["tasks"]), 1)
            create_rows = [row for row in state_value["outbox"].values() if row["kind"] == "CREATE_THREAD"]
            self.assertEqual(len(create_rows), 1)


if __name__ == "__main__":
    unittest.main()
