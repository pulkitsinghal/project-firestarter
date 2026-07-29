from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "pre_tool_use_root_guard.py"


def invoke(tool_name: str, *, root: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if root:
        env["ROOT_ORCHESTRATOR_ROLE"] = "true"
    else:
        env.pop("ROOT_ORCHESTRATOR_ROLE", None)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "synthetic-session",
                "turn_id": "synthetic-turn",
                "tool_use_id": f"call-{tool_name}",
                "tool_name": tool_name,
                "tool_input": {"synthetic": True},
            }
        ),
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=5,
    )


class PreToolUseHookTest(unittest.TestCase):
    def test_root_task_domain_families_are_denied_before_synthetic_dispatch(self):
        calls: list[str] = []
        tools = (
            "Bash",
            "apply_patch",
            "Agent",
            "mcp__filesystem__write_file",
            "mcp__codex_apps__browser_click",
            "mcp__codex_apps__sites_create_version",
        )
        for tool_name in tools:
            result = invoke(tool_name)
            self.assertEqual(0, result.returncode, result.stderr)
            decision = json.loads(result.stdout)
            self.assertEqual(
                "deny",
                decision["hookSpecificOutput"]["permissionDecision"],
            )
            if decision["hookSpecificOutput"]["permissionDecision"] != "deny":
                calls.append(tool_name)
        self.assertEqual([], calls)

    def test_unknown_and_invalid_events_fail_closed(self):
        unknown = invoke("new_specialized_local_tool")
        self.assertIn("UNKNOWN_TOOL_DENIED", unknown.stdout)
        invalid = subprocess.run(
            [sys.executable, str(HOOK)],
            input="not-json",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertIn("ROOT_GUARD_INVALID_EVENT", invalid.stdout)

    def test_control_plane_allowed_and_nonroot_has_no_decision(self):
        self.assertEqual("", invoke("codex_app__list_threads").stdout)
        self.assertEqual("", invoke("Bash", root=False).stdout)

    def test_denial_prevents_synthetic_canary(self):
        with tempfile.TemporaryDirectory(prefix="pm-proxy-hook-proof-") as temp:
            canary = Path(temp) / "should-not-exist"
            decision = json.loads(invoke("Bash").stdout)
            if decision["hookSpecificOutput"]["permissionDecision"] != "deny":
                canary.write_text("underlying executor ran", encoding="utf-8")
            self.assertFalse(canary.exists())


if __name__ == "__main__":
    unittest.main()
