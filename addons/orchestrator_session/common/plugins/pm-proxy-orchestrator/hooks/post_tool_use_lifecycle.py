#!/usr/bin/env python3
"""Record and clear covered-path lifecycle reconciliation debts."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - supported orchestrator hosts are POSIX
    fcntl = None


ROOT_TRUE = {"1", "true", "yes", "root", "trusted-project-hook"}
OBSERVATION_TOOLS = {
    "codex_app__read_thread",
    "codex_app__wait_threads",
    "codex_appread_thread",
    "codex_appwait_threads",
}
LIFECYCLE_TOOL = "mcp__pm_proxy_orchestrator__pm_proxy_lifecycle_watchdog"
LOCK_TIMEOUT_SECONDS = 0.25
LOCK_RETRY_SECONDS = 0.01
MAX_LIFECYCLE_SESSIONS = 512
MAX_WORKERS_PER_SESSION = 64


def state_root() -> Path | None:
    root = Path.home() / ".codex" / "orchestrator-state"
    try:
        if root.is_symlink() or (root.stat().st_mode & 0o777) != 0o700:
            return None
    except OSError:
        return None
    return root


def worker_ids(tool_name: str, tool_input: Any) -> list[str]:
    if not isinstance(tool_input, dict):
        return []
    if tool_name in {"codex_app__read_thread", "codex_appread_thread"}:
        value = tool_input.get("threadId") or tool_input.get("thread_id")
        return [value] if isinstance(value, str) and value else []
    if tool_name in {"codex_app__wait_threads", "codex_appwait_threads"}:
        targets = tool_input.get("targets")
        if not isinstance(targets, list):
            return []
        values: list[str] = []
        for target in targets:
            if not isinstance(target, dict):
                return []
            value = target.get("threadId") or target.get("thread_id")
            if not isinstance(value, str) or not value:
                return []
            values.append(value)
        return sorted(set(values))
    return []


def response_ok(value: Any) -> bool:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return False
    if not isinstance(value, dict) or value.get("isError") is True:
        return False
    if "structuredContent" in value:
        structured = value["structuredContent"]
        return isinstance(structured, dict) and structured.get("ok") is True
    wrapped = value.get("result")
    if not isinstance(wrapped, dict) or wrapped.get("isError") is True:
        return False
    structured = wrapped.get("structuredContent")
    return isinstance(structured, dict) and structured.get("ok") is True


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
        raise OSError("lifecycle lock is not a private regular file")
    return descriptor


def update(session_id: str, add: list[str], remove: str | None) -> bool:
    root = state_root()
    if root is None or fcntl is None:
        return False
    lock_path = root / ".dispatcher-lifecycle.lock"
    ledger_path = root / ".dispatcher-lifecycle.json"
    try:
        descriptor = open_private_lock(lock_path)
        with os.fdopen(descriptor, "r+", encoding="utf-8") as lock:
            if not acquire_lock(lock):
                return False
            if ledger_path.exists():
                if ledger_path.is_symlink() or (ledger_path.stat().st_mode & 0o777) != 0o600:
                    return False
                ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
                if not isinstance(ledger, dict):
                    return False
            else:
                ledger = {}
            current = ledger.get(session_id, [])
            if not isinstance(current, list) or not all(
                isinstance(item, str) for item in current
            ):
                return False
            pending = set(current)
            pending.update(add)
            if remove is not None:
                pending.discard(remove)
            if add and len(pending) > MAX_WORKERS_PER_SESSION:
                return False
            if add and session_id not in ledger and len(ledger) >= MAX_LIFECYCLE_SESSIONS:
                return False
            if pending:
                ledger[session_id] = sorted(pending)
            else:
                ledger.pop(session_id, None)
            temporary_descriptor, temporary = tempfile.mkstemp(
                prefix=".dispatcher-lifecycle.", dir=root
            )
            temporary_path = Path(temporary)
            try:
                os.fchmod(temporary_descriptor, 0o600)
                with os.fdopen(
                    temporary_descriptor, "w", encoding="utf-8"
                ) as handle:
                    temporary_descriptor = -1
                    json.dump(ledger, handle, sort_keys=True, separators=(",", ":"))
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, ledger_path)
            finally:
                if temporary_descriptor >= 0:
                    os.close(temporary_descriptor)
                temporary_path.unlink(missing_ok=True)
            return True
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def main() -> int:
    if os.environ.get("ROOT_ORCHESTRATOR_ROLE", "").strip().lower() not in ROOT_TRUE:
        return 0
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 1
    if event.get("hook_event_name") != "PostToolUse":
        return 1
    session_id = event.get("session_id")
    tool_name = event.get("tool_name")
    if not isinstance(session_id, str) or not session_id or not isinstance(tool_name, str):
        return 1
    if tool_name in OBSERVATION_TOOLS:
        ids = worker_ids(tool_name, event.get("tool_input"))
        return 0 if ids and update(session_id, ids, None) else 1
    if tool_name == LIFECYCLE_TOOL:
        tool_input = event.get("tool_input")
        if not isinstance(tool_input, dict):
            return 1
        external_id = tool_input.get("external_thread_id")
        if not isinstance(external_id, str) or not response_ok(
            event.get("tool_response")
        ):
            return 1
        return 0 if update(session_id, [], external_id) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
