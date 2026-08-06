#!/usr/bin/env python3
"""Record and clear covered-path lifecycle reconciliation debts."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
from enum import Enum
from pathlib import Path
from typing import Any

from host_attestation import HostAttestationError, configured, resolve

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
CONTROL_SCHEMA_HOLD_TOOL = (
    "mcp__pm_proxy_orchestrator__pm_proxy_acknowledge_control_schema_hold"
)
LOCK_TIMEOUT_SECONDS = 0.25
LOCK_RETRY_SECONDS = 0.01
MAX_LIFECYCLE_SESSIONS = 512
MAX_WORKERS_PER_SESSION = 64
MAX_IDENTITY_TICKETS = 4096
OWNER_DECISION_SINK_THREAD_ID = "019fcb3b-f5dc-7df3-9fe1-efe5b2e09a69"


class IdentityKind(str, Enum):
    """Closed identity classes used by the lifecycle fence."""

    OWNER_DECISION_SINK = "OWNER_DECISION_SINK"
    RECEIPTED_TASK = "RECEIPTED_TASK"
    UNKNOWN = "UNKNOWN"
    MISMATCH = "MISMATCH"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


def state_root() -> Path | None:
    root = Path.home() / ".codex" / "orchestrator-state"
    try:
        metadata = root.stat()
        if (
            root.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or (metadata.st_mode & 0o777) != 0o700
        ):
            return None
    except OSError:
        return None
    return root


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


def private_identity_state_dirs() -> list[Path] | None:
    root = state_root()
    if root is None:
        return None
    try:
        candidates = list(root.iterdir())
    except OSError:
        return None
    result: list[Path] = []
    for candidate in candidates:
        try:
            if candidate.is_symlink():
                return None
            if not candidate.is_dir():
                continue
            metadata = candidate.stat()
            if metadata.st_uid != os.getuid() or (metadata.st_mode & 0o777) != 0o700:
                return None
            result.append(candidate)
        except OSError:
            return None
    return result


def private_ticket(path: Path) -> dict[str, Any] | None:
    try:
        metadata = path.stat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or (metadata.st_mode & 0o777) != 0o600
            or metadata.st_size > 2_000_000
        ):
            return None
        return strict_object(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def classify_identities(
    external_thread_ids: list[str],
) -> dict[str, IdentityKind] | None:
    """Classify identities from one bounded read-only receipt snapshot."""

    if not external_thread_ids or not all(
        isinstance(item, str) and item for item in external_thread_ids
    ):
        return None
    matching_receipts = {item: 0 for item in external_thread_ids}
    failed = {
        item: IdentityKind.VERIFICATION_FAILED for item in external_thread_ids
    }
    states = private_identity_state_dirs()
    if states is None:
        return failed
    observed_tickets = 0
    for state in states:
        try:
            tickets = list(state.glob("*.ticket.json"))
        except OSError:
            return failed
        observed_tickets += len(tickets)
        if observed_tickets > MAX_IDENTITY_TICKETS:
            return failed
        for path in tickets:
            ticket = private_ticket(path)
            if ticket is None:
                return failed
            if "receipt" not in ticket:
                return failed
            receipt = ticket.get("receipt")
            if receipt is None:
                continue
            receipt_id = (
                receipt.get("external_thread_id")
                if isinstance(receipt, dict)
                else None
            )
            if not isinstance(receipt_id, str) or not receipt_id:
                return failed
            if receipt_id in matching_receipts:
                matching_receipts[receipt_id] += 1
    classified: dict[str, IdentityKind] = {}
    for external_thread_id, receipt_count in matching_receipts.items():
        if external_thread_id == OWNER_DECISION_SINK_THREAD_ID:
            classified[external_thread_id] = (
                IdentityKind.OWNER_DECISION_SINK
                if receipt_count == 0
                else IdentityKind.MISMATCH
            )
        elif receipt_count == 1:
            classified[external_thread_id] = IdentityKind.RECEIPTED_TASK
        elif receipt_count > 1:
            classified[external_thread_id] = IdentityKind.MISMATCH
        else:
            classified[external_thread_id] = IdentityKind.UNKNOWN
    return classified


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


def lifecycle_worker_ids(tool_name: str, tool_input: Any) -> list[str] | None:
    """Return debt-bearing identities, excluding only a proven decision sink."""

    observed = worker_ids(tool_name, tool_input)
    if not observed:
        return None
    classified = classify_identities(observed)
    if classified is None:
        return None
    workers: list[str] = []
    for external_thread_id in observed:
        identity = classified[external_thread_id]
        if identity == IdentityKind.OWNER_DECISION_SINK:
            continue
        if identity in {IdentityKind.MISMATCH, IdentityKind.VERIFICATION_FAILED}:
            return None
        workers.append(external_thread_id)
    return workers


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


def response_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, dict) or value.get("isError") is True:
        return None
    structured = value.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    wrapped = value.get("result")
    if not isinstance(wrapped, dict) or wrapped.get("isError") is True:
        return None
    structured = wrapped.get("structuredContent")
    return structured if isinstance(structured, dict) else None


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


def read_lifecycle_ledger(path: Path) -> dict[str, Any] | None:
    try:
        metadata = path.stat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or (metadata.st_mode & 0o777) != 0o600
            or metadata.st_size > 2_000_000
        ):
            return None
        ledger = strict_object(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    if ledger is None or len(ledger) > MAX_LIFECYCLE_SESSIONS:
        return None
    for session_id, pending in ledger.items():
        if (
            not isinstance(session_id, str)
            or not session_id
            or not isinstance(pending, list)
            or len(pending) > MAX_WORKERS_PER_SESSION
            or not all(isinstance(item, str) and item for item in pending)
            or len(set(pending)) != len(pending)
        ):
            return None
    return ledger


def write_lifecycle_ledger(
    root: Path, ledger_path: Path, ledger: dict[str, Any]
) -> bool:
    temporary_descriptor, temporary = tempfile.mkstemp(
        prefix=".dispatcher-lifecycle.", dir=root
    )
    temporary_path = Path(temporary)
    try:
        os.fchmod(temporary_descriptor, 0o600)
        with os.fdopen(temporary_descriptor, "w", encoding="utf-8") as handle:
            temporary_descriptor = -1
            json.dump(ledger, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, ledger_path)
        return True
    except OSError:
        return False
    finally:
        if temporary_descriptor >= 0:
            os.close(temporary_descriptor)
        temporary_path.unlink(missing_ok=True)


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
                ledger = read_lifecycle_ledger(ledger_path)
                if ledger is None:
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
            return write_lifecycle_ledger(root, ledger_path, ledger)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def migrate_legacy_lifecycle_debt(session_id: Any) -> list[str] | None:
    """Remove only a legacy pending identity proven to be the non-task sink."""

    if not isinstance(session_id, str) or not session_id:
        return None
    root = state_root()
    if root is None or fcntl is None:
        return None
    lock_path = root / ".dispatcher-lifecycle.lock"
    ledger_path = root / ".dispatcher-lifecycle.json"
    if not ledger_path.exists():
        return []
    try:
        descriptor = open_private_lock(lock_path)
        with os.fdopen(descriptor, "r+", encoding="utf-8") as lock:
            if not acquire_lock(lock):
                return None
            ledger = read_lifecycle_ledger(ledger_path)
            if ledger is None:
                return None
            current = ledger.get(session_id, [])
            if not current:
                return []
            classified = classify_identities(current)
            if classified is None or any(
                identity == IdentityKind.VERIFICATION_FAILED
                for identity in classified.values()
            ):
                return None
            retained: list[str] = []
            changed = False
            for external_thread_id in current:
                identity = classified[external_thread_id]
                if identity == IdentityKind.OWNER_DECISION_SINK:
                    changed = True
                    continue
                retained.append(external_thread_id)
            if changed:
                if retained:
                    ledger[session_id] = retained
                else:
                    ledger.pop(session_id, None)
                if not write_lifecycle_ledger(root, ledger_path, ledger):
                    return None
            return retained
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def main() -> int:
    legacy_root = (
        os.environ.get("ROOT_ORCHESTRATOR_ROLE", "").strip().lower() in ROOT_TRUE
    )
    if not legacy_root and not configured():
        return 0
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 1
    if event.get("hook_event_name") != "PostToolUse":
        return 1
    if not legacy_root:
        try:
            host_role = resolve(event)
        except HostAttestationError:
            return 1
        if host_role != "ROOT":
            return 0
    session_id = event.get("session_id")
    tool_name = event.get("tool_name")
    if not isinstance(session_id, str) or not session_id or not isinstance(tool_name, str):
        return 1
    if tool_name in OBSERVATION_TOOLS:
        ids = lifecycle_worker_ids(tool_name, event.get("tool_input"))
        if ids is None:
            return 1
        return 0 if not ids or update(session_id, ids, None) else 1
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
    if tool_name == CONTROL_SCHEMA_HOLD_TOOL:
        tool_input = event.get("tool_input")
        payload = response_payload(event.get("tool_response"))
        result = payload.get("result") if isinstance(payload, dict) else None
        grant = (
            result.get("bootstrap_recovery_grant")
            if isinstance(result, dict)
            else None
        )
        external_id = (
            tool_input.get("external_thread_id")
            if isinstance(tool_input, dict)
            else None
        )
        if (
            not isinstance(external_id, str)
            or not external_id
            or not isinstance(payload, dict)
            or payload.get("ok") is not True
            or payload.get("operation") != "acknowledge-control-schema-hold"
            or not isinstance(result, dict)
            or result.get("external_thread_id") != external_id
            or result.get("hold_state") != "CONTROL_SCHEMA_HOLD"
            or result.get("required_action") != "AWAIT_CONTROL_REPAIR"
            or not isinstance(grant, dict)
            or grant.get("status") != "REVOKED"
            or grant.get("consumed_before_dispatch") is not True
            or grant.get("host_attested") is not True
        ):
            return 1
        return 0 if update(session_id, [], external_id) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
