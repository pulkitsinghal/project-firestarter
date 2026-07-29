#!/usr/bin/env python3
"""Covered-path Codex PreToolUse guard; not universal role enforcement."""

from __future__ import annotations

import json
import os
import sys
from typing import Any


ROOT_TRUE = {"1", "true", "yes", "root"}
ROOT_CONTROL_PLANE_ALLOW = {
    "codex_app__list_threads",
    "codex_app__read_thread",
    "codex_app__wait_threads",
    "codex_app__send_message_to_thread",
    "codex_app__set_thread_archived",
    "codex_app__create_thread",
    "update_plan",
}
PROTECTED_EXACT = {
    "Bash",
    "apply_patch",
    "Agent",
    "spawn_agent",
    "write_stdin",
}
PROTECTED_PREFIXES = (
    "mcp__codex_apps__sites_",
    "mcp__codex_apps__browser_",
    "mcp__codex_apps__chrome_",
    "mcp__codex_apps__computer_",
    "mcp__filesystem__",
    "browser__",
    "chrome__",
    "computer_use__",
    "sites__",
)


def deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def protected(tool_name: str) -> bool:
    return tool_name in PROTECTED_EXACT or tool_name.startswith(PROTECTED_PREFIXES)


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        print(json.dumps(deny("ROOT_GUARD_INVALID_EVENT")))
        return 0
    if event.get("hook_event_name") != "PreToolUse":
        print(json.dumps(deny("ROOT_GUARD_WRONG_EVENT")))
        return 0
    role = os.environ.get("ROOT_ORCHESTRATOR_ROLE", "").strip().lower()
    if role not in ROOT_TRUE:
        return 0
    tool_name = event.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name:
        print(json.dumps(deny("ROOT_GUARD_TOOL_ID_MISSING")))
        return 0
    if tool_name in ROOT_CONTROL_PLANE_ALLOW:
        return 0
    if protected(tool_name):
        print(json.dumps(deny(f"ROOT_ORCHESTRATOR_TASK_DOMAIN_DENIED:{tool_name}")))
        return 0
    print(json.dumps(deny(f"ROOT_ORCHESTRATOR_UNKNOWN_TOOL_DENIED:{tool_name}")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
