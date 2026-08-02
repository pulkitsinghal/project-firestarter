#!/usr/bin/env python3
"""Covered-path Codex PreToolUse guard; not universal role enforcement."""

from __future__ import annotations

import json
import os
import re
import stat
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - supported orchestrator hosts are POSIX
    fcntl = None

try:
    from post_tool_use_lifecycle import (
        OBSERVATION_TOOLS,
        update as update_lifecycle,
        worker_ids,
    )
except ImportError:  # keep doctor/status reachable on an incomplete hook install
    OBSERVATION_TOOLS = {
        "codex_app__read_thread",
        "codex_app__wait_threads",
        "codex_appread_thread",
        "codex_appwait_threads",
    }

    def worker_ids(tool_name: str, tool_input: Any) -> list[str]:
        del tool_name, tool_input
        return []

    def update_lifecycle(session_id: str, add: list[str], remove: str | None) -> bool:
        del session_id, add, remove
        return False


ROOT_TRUE = {"1", "true", "yes", "root", "trusted-project-hook"}
ROOT_CONTROL_PLANE_ALLOW = {
    "codex_app__list_threads",
    "codex_app__list_projects",
    "codex_app__read_thread",
    "codex_app__wait_threads",
    "codex_app__send_message_to_thread",
    "codex_app__set_thread_archived",
    "codex_app__create_thread",
    "update_plan",
    "codex_applist_threads",
    "codex_applist_projects",
    "codex_appread_thread",
    "codex_appwait_threads",
    "codex_appsend_message_to_thread",
    "codex_appset_thread_archived",
    "codex_appcreate_thread",
}
ROOT_CONTROL_PLANE_MCP_ALLOW = {
    "mcp__pm_proxy_orchestrator__pm_proxy_close_and_refill",
    "mcp__pm_proxy_orchestrator__pm_proxy_doctor",
    "mcp__pm_proxy_orchestrator__pm_proxy_heartbeat",
    "mcp__pm_proxy_orchestrator__pm_proxy_lifecycle_watchdog",
    "mcp__pm_proxy_orchestrator__pm_proxy_prepare_launch",
    "mcp__pm_proxy_orchestrator__pm_proxy_record_archive_receipt",
    "mcp__pm_proxy_orchestrator__pm_proxy_record_dispatcher_adoption",
    "mcp__pm_proxy_orchestrator__pm_proxy_record_launch_receipt",
    "mcp__pm_proxy_orchestrator__pm_proxy_record_refill_receipt",
    "mcp__pm_proxy_orchestrator__pm_proxy_reconcile_expired_lease",
    "mcp__pm_proxy_orchestrator__pm_proxy_slot_status",
    "mcp__pm_proxy_orchestrator__pm_proxy_status",
    "mcp__pm_proxy_orchestrator__pm_proxy_verify_runtime",
    "mcp__pm_proxy_orchestrator__pm_proxy_watchdog_refill",
}
LIFECYCLE_TOOL = "mcp__pm_proxy_orchestrator__pm_proxy_lifecycle_watchdog"
LIFECYCLE_DEBT_BLOCKED_TOOLS = {
    "codex_app__read_thread",
    "codex_app__wait_threads",
    "codex_app__create_thread",
    "codex_app__set_thread_archived",
    "mcp__pm_proxy_orchestrator__pm_proxy_status",
    "mcp__pm_proxy_orchestrator__pm_proxy_slot_status",
    "mcp__pm_proxy_orchestrator__pm_proxy_watchdog_refill",
    "codex_appread_thread",
    "codex_appwait_threads",
    "codex_appcreate_thread",
    "codex_appset_thread_archived",
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
ENVELOPE = re.compile(
    r"\n<orchestrator_launch_envelope>\n(?P<body>\{.*\})\n"
    r"</orchestrator_launch_envelope>\Z",
    re.DOTALL,
)
ARCHIVE_READY_OUTCOMES = {
    "REFILL_SATISFIED",
    "EMPTY",
    "OWNER_GATED",
    "CAPACITY_FULL",
}
LOCK_TIMEOUT_SECONDS = 0.25
LOCK_RETRY_SECONDS = 0.01
MAX_ADMISSIONS = 512


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


def strict_object(raw: str) -> dict[str, Any] | None:
    def no_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=no_duplicate)
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def private_state_dirs() -> list[Path]:
    root = Path.home() / ".codex" / "orchestrator-state"
    try:
        if root.is_symlink() or (root.stat().st_mode & 0o777) != 0o700:
            return []
    except OSError:
        return []
    result: list[Path] = []
    try:
        candidates = list(root.iterdir())
    except OSError:
        return []
    for candidate in candidates:
        try:
            if (
                candidate.is_dir()
                and not candidate.is_symlink()
                and (candidate.stat().st_mode & 0o777) == 0o700
            ):
                result.append(candidate)
        except OSError:
            continue
    return result


def read_private_json(path: Path) -> dict[str, Any] | None:
    try:
        if (
            not path.is_file()
            or path.is_symlink()
            or (path.stat().st_mode & 0o777) != 0o600
            or path.stat().st_size > 2_000_000
        ):
            return None
        return strict_object(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def lifecycle_debt(session_id: Any) -> list[str] | None:
    if not isinstance(session_id, str) or not session_id:
        return None
    root = Path.home() / ".codex" / "orchestrator-state"
    ledger_path = root / ".dispatcher-lifecycle.json"
    if not ledger_path.exists():
        return []
    ledger = read_private_json(ledger_path)
    if ledger is None:
        return None
    pending = ledger.get(session_id, [])
    if not isinstance(pending, list) or not all(
        isinstance(item, str) and item for item in pending
    ):
        return None
    return pending


def fresh_unreceipted(ticket: dict[str, Any]) -> bool:
    if ticket.get("receipt") is not None:
        return False
    deadline = ticket.get("receipt_deadline")
    if not isinstance(deadline, str) or not deadline.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(deadline[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed >= datetime.now(timezone.utc)


def matching_launch(prompt: Any) -> tuple[Path, dict[str, Any]] | None:
    if not isinstance(prompt, str) or len(prompt.encode("utf-8")) > 1_000_000:
        return None
    matched = ENVELOPE.search(prompt)
    if matched is None:
        return None
    envelope = strict_object(matched.group("body"))
    if envelope is None:
        return None
    required = (
        "task_id",
        "source_event_key",
        "outcome_key",
        "policy_snapshot_revision",
        "lease_epoch",
        "fencing_token",
    )
    matches: list[tuple[Path, dict[str, Any]]] = []
    for state in private_state_dirs():
        try:
            tickets = list(state.glob("*.ticket.json"))
        except OSError:
            continue
        for path in tickets:
            ticket = read_private_json(path)
            if ticket is None:
                continue
            if any(ticket.get(key) != envelope.get(key) for key in required):
                continue
            outbox = ticket.get("outbox")
            if not isinstance(outbox, dict) or outbox.get("kind") != "CREATE_THREAD":
                continue
            matches.append((state, ticket))
    return matches[0] if len(matches) == 1 else None


def archive_ready(external_thread_id: Any) -> tuple[Path, dict[str, Any]] | None:
    if not isinstance(external_thread_id, str) or not external_thread_id:
        return None
    matches: list[tuple[Path, dict[str, Any]]] = []
    for state in private_state_dirs():
        try:
            tickets = list(state.glob("*.ticket.json"))
        except OSError:
            continue
        for path in tickets:
            ticket = read_private_json(path)
            if ticket is None or not isinstance(ticket.get("handback"), dict):
                continue
            receipt = ticket.get("receipt")
            if not isinstance(receipt, dict) or receipt.get("external_thread_id") != external_thread_id:
                continue
            if ticket_archive_ready(state, ticket):
                matches.append((state, ticket))
    return matches[0] if len(matches) == 1 else None


def ticket_archive_ready(state: Path, ticket: dict[str, Any]) -> bool:
    handback = ticket.get("handback")
    if not isinstance(handback, dict) or handback.get("archive_receipt_at") is not None:
        return False
    task_id = ticket.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        return False
    ledger = read_private_json(state / "pm-proxy-refill-ledger.json")
    if ledger is None or not isinstance(ledger.get("sagas"), dict):
        return False
    return any(
        isinstance(saga, dict)
        and saga.get("predecessor_task_id") == task_id
        and saga.get("outcome") in ARCHIVE_READY_OUTCOMES
        for saga in ledger["sagas"].values()
    )


def active_admission_keys(state: Path) -> set[str] | None:
    active: set[str] = set()
    try:
        tickets = list(state.glob("*.ticket.json"))
    except OSError:
        return None
    for path in tickets:
        ticket = read_private_json(path)
        if ticket is None:
            return None
        outbox = ticket.get("outbox")
        if isinstance(outbox, dict) and outbox.get("kind") == "CREATE_THREAD":
            outbox_id = outbox.get("outbox_id")
            if isinstance(outbox_id, str) and outbox_id and fresh_unreceipted(ticket):
                active.add(f"create:{outbox_id}")
        task_id = ticket.get("task_id")
        if isinstance(task_id, str) and ticket_archive_ready(state, ticket):
            active.add(f"archive:{task_id}")
    return active


def acquire_lock(handle: Any) -> bool:
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(LOCK_RETRY_SECONDS)


def open_private_lock(path: Path) -> int:
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or (metadata.st_mode & 0o777) != 0o600:
        os.close(descriptor)
        raise OSError("admission lock is not a private regular file")
    return descriptor


def admit_once(state: Path, action_key: str, tool_use_id: Any) -> str:
    if not isinstance(tool_use_id, str) or not tool_use_id:
        return "INVALID"
    lock_path = state / ".dispatcher-admissions.lock"
    ledger_path = state / ".dispatcher-admissions.json"
    try:
        descriptor = open_private_lock(lock_path)
        with os.fdopen(descriptor, "r+", encoding="utf-8") as lock:
            if fcntl is None:
                return "INVALID"
            if not acquire_lock(lock):
                return "BUSY"
            ledger = read_private_json(ledger_path) if ledger_path.exists() else {}
            if ledger is None:
                return "INVALID"
            active = active_admission_keys(state)
            if active is None:
                return "INVALID"
            ledger = {key: value for key, value in ledger.items() if key in active}
            existing = ledger.get(action_key)
            if existing is not None:
                if not isinstance(existing, str):
                    return "INVALID"
                return "ADMITTED" if existing == tool_use_id else "REPLAY"
            if len(ledger) >= MAX_ADMISSIONS:
                return "FULL"
            ledger[action_key] = tool_use_id
            descriptor, temporary = tempfile.mkstemp(
                prefix=".dispatcher-admissions.", dir=state
            )
            temporary_path = Path(temporary)
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    descriptor = -1
                    json.dump(ledger, handle, sort_keys=True, separators=(",", ":"))
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, ledger_path)
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
                temporary_path.unlink(missing_ok=True)
            return "ADMITTED"
    except OSError:
        return "INVALID"


def admission_denial(kind: str, outcome: str) -> dict[str, Any] | None:
    if outcome == "ADMITTED":
        return None
    if outcome == "REPLAY":
        return deny(f"ROOT_{kind}_ALREADY_ADMITTED")
    return deny(f"ROOT_ADMISSION_{outcome}")


def control_plane_decision(event: dict[str, Any], tool_name: str) -> dict[str, Any] | None:
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return deny("ROOT_CONTROL_INPUT_INVALID")
    if tool_name in {"codex_app__create_thread", "codex_appcreate_thread"}:
        matched = matching_launch(tool_input.get("prompt"))
        if matched is None:
            return deny("ROOT_CREATE_RESERVATION_REQUIRED")
        state, ticket = matched
        if ticket.get("receipt") is not None:
            return deny("ROOT_CREATE_ALREADY_ADMITTED")
        if not fresh_unreceipted(ticket):
            return deny("ROOT_CREATE_RESERVATION_REQUIRED")
        outbox = ticket["outbox"]
        return admission_denial(
            "CREATE",
            admit_once(
                state,
                f"create:{outbox.get('outbox_id')}",
                event.get("tool_use_id"),
            ),
        )
    if tool_name in {
        "codex_app__set_thread_archived",
        "codex_appset_thread_archived",
    }:
        if tool_input.get("archived") is not True:
            return deny("ROOT_UNARCHIVE_DENIED")
        matched = archive_ready(tool_input.get("threadId") or tool_input.get("thread_id"))
        if matched is None:
            return deny("ROOT_ARCHIVE_REFILL_FENCE_REQUIRED")
        state, ticket = matched
        return admission_denial(
            "ARCHIVE",
            admit_once(
                state,
                f"archive:{ticket.get('task_id')}",
                event.get("tool_use_id"),
            ),
        )
    return None


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
    pending = lifecycle_debt(event.get("session_id"))
    if pending is None:
        print(json.dumps(deny("ROOT_LIFECYCLE_STATE_INVALID")))
        return 0
    if pending and tool_name in LIFECYCLE_DEBT_BLOCKED_TOOLS:
        print(json.dumps(deny("ROOT_LIFECYCLE_RECONCILIATION_REQUIRED")))
        return 0
    if tool_name in OBSERVATION_TOOLS:
        ids = worker_ids(tool_name, event.get("tool_input"))
        if not ids or not update_lifecycle(event["session_id"], ids, None):
            print(json.dumps(deny("ROOT_LIFECYCLE_STATE_BUSY")))
            return 0
    if tool_name in ROOT_CONTROL_PLANE_ALLOW:
        decision = control_plane_decision(event, tool_name)
        if decision is not None:
            print(json.dumps(decision))
            return 0
        return 0
    if tool_name in ROOT_CONTROL_PLANE_MCP_ALLOW:
        return 0
    if protected(tool_name):
        print(json.dumps(deny(f"ROOT_ORCHESTRATOR_TASK_DOMAIN_DENIED:{tool_name}")))
        return 0
    print(json.dumps(deny(f"ROOT_ORCHESTRATOR_UNKNOWN_TOOL_DENIED:{tool_name}")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
