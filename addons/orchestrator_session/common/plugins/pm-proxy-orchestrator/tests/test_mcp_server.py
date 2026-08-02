from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests.support import BRIDGE, iso, launch_request, private_temp, recycle_request


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER = PLUGIN_ROOT / "scripts" / "mcp_server.py"


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

    def test_doctor_and_prepare_launch_use_typed_private_surface(self) -> None:
        doctor = self.call("pm_proxy_doctor", self.common(), include_meta=True)
        tool_result = doctor["result"]
        self.assertIsNot(tool_result.get("isError"), True)
        self.assertEqual("1.3", tool_result["structuredContent"]["result"]["schema_version"])
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
        adopted = self.call(
            "pm_proxy_record_dispatcher_adoption",
            {**self.common(), "request": adoption_request},
        )
        self.assertIsNot(adopted["result"].get("isError"), True, adopted)
        current = self.call("pm_proxy_status", self.common())
        lifecycle = current["result"]["structuredContent"]["result"][
            "lifecycle_watchdog"
        ]
        self.assertTrue(lifecycle["covered_path_dispatcher_enforcement"])
        self.assertFalse(lifecycle["platform_dispatcher_enforcement"])

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
