#!/usr/bin/env python3
"""Bounded, partitioned, resumable execution for trusted project commands."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Iterator
import uuid

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - generated projects require Python 3.11+
    tomllib = None  # type: ignore[assignment]


OK = "OK"
SKIPPED = "SKIPPED"
FAIL = "FAIL"
TIMEOUT = "TIMEOUT"
STALLED = "STALLED"
BLOCKED = "BLOCKED"
KILLED = "KILLED"
MISSING = "MISSING"
GOOD = {OK, SKIPPED}
PENDING = "PENDING"
STATUSES = {OK, SKIPPED, FAIL, TIMEOUT, STALLED, BLOCKED, KILLED, PENDING}
SCHEMA = 1
MAX_STATE_BYTES = 1024 * 1024
ROOT_MARKER = ".bounded-runner-root"
ROOT_MARKER_CONTENT = "bounded-runner-root-v1\n"
HOST = socket.gethostname()
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
SAFE_ENV = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
GLOB_CHARS = set("*?[]{}")
RESERVED_ENV = {
    "RUNNER_RUN",
    "RUNNER_UNIT_ID",
    "RUNNER_DEADLINE_S",
    "RUNNER_CHECKPOINT",
    "RUNNER_HEARTBEAT",
    "RUNNER_FINGERPRINT",
}
BASE_ENV = {
    "PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
    "TMP", "TEMP", "TMPDIR", "LANG", "LC_ALL",
}
TOP_KEYS = {"run", "defaults", "unit"}
RUN_KEYS = {"name", "root", "state", "worker_budget", "poll_interval_s"}
UNIT_KEYS = {
    "id",
    "cmd",
    "cwd",
    "write_paths",
    "readonly",
    "deadline_s",
    "grace_s",
    "heartbeat_stall_s",
    "checkpoint",
    "verify",
    "verify_deadline_s",
    "workers",
    "required",
    "env",
    "inherit_env",
    "input_revision",
    "note",
}
RECORD_KEYS = {
    "schema", "id", "run", "status", "reason", "required", "workers", "write_paths",
    "deadline_s", "exit_code", "pid", "started_at", "ended_at", "duration_s", "attempt",
    "checkpoint", "checkpoint_complete", "checkpoint_state", "log", "fingerprint",
    "invocation", "evidence",
}


class SpecError(ValueError):
    pass


class StateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Unit:
    id: str
    cmd: tuple[str, ...]
    cwd: Path
    owns: tuple[Path, ...]
    deadline_s: float
    grace_s: float
    workers: int
    required: bool
    readonly: bool
    checkpoint: Path | None = None
    heartbeat_stall_s: float | None = None
    verify: tuple[str, ...] | None = None
    verify_deadline_s: float = 300.0
    env: dict[str, str] = field(default_factory=dict)
    inherit_env: tuple[str, ...] = ()
    input_revision: str | None = None
    note: str = ""


@dataclass
class RunSpec:
    name: str
    root: Path
    state: Path
    worker_budget: int
    poll_interval_s: float
    units: tuple[Unit, ...]
    spec_path: Path
    spec_sha256: str

    @property
    def run_dir(self) -> Path:
        return self.state / "runs" / self.name

    @property
    def units_dir(self) -> Path:
        return self.run_dir / "units"

    @property
    def logs_dir(self) -> Path:
        return self.run_dir / "logs"

    @property
    def heartbeats_dir(self) -> Path:
        return self.run_dir / "heartbeats"

    @property
    def lock_root(self) -> Path:
        # Fixed under run.root so choosing a different record directory cannot bypass admission.
        return self.root / ".bounded-runner-locks"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def strict_number(value: Any, label: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecError(f"{label} must be a number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise SpecError(f"{label} must be a finite number") from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise SpecError(f"{label} must be between {minimum:g} and {maximum:g}")
    return result


def strict_int(value: Any, label: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SpecError(f"{label} must be an integer")
    if not minimum <= value <= maximum:
        raise SpecError(f"{label} must be between {minimum} and {maximum}")
    return value


def strict_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise SpecError(f"{label} must be true or false")
    return value


def argv(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise SpecError(f"{label} must be a non-empty argv array, never a shell string")
    if any(not isinstance(part, str) or not part or "\0" in part for part in value):
        raise SpecError(f"{label} entries must be non-empty strings without NUL bytes")
    return tuple(value)


def confined(root: Path, value: Any, label: str, *, must_exist_dir: bool = False) -> Path:
    if not isinstance(value, str) or not value:
        raise SpecError(f"{label} must be a non-empty relative path")
    if Path(value).is_absolute():
        raise SpecError(f"{label} must be relative to the declared root")
    if any(char in value for char in GLOB_CHARS):
        raise SpecError(f"{label} must not contain glob characters")
    result = (root / value).resolve()
    try:
        result.relative_to(root)
    except ValueError as exc:
        raise SpecError(f"{label} escapes the declared root") from exc
    if must_exist_dir and not result.is_dir():
        raise SpecError(f"{label} is not an existing directory")
    return result


def overlaps(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def canonical_project_root(declared_root: Path) -> Path:
    for candidate in (declared_root, *declared_root.parents):
        marker = candidate / ROOT_MARKER
        if marker.is_symlink():
            raise SpecError(f"{ROOT_MARKER} must not be a symlink")
        if marker.is_file():
            try:
                content = marker.read_text(encoding="utf-8")
            except OSError as exc:
                raise SpecError(f"could not read {ROOT_MARKER}") from exc
            if content != ROOT_MARKER_CONTENT:
                raise SpecError(f"{ROOT_MARKER} has an unsupported format")
            return candidate.resolve()
    raise SpecError(
        f"run.root must be the project directory containing the stamped {ROOT_MARKER}"
    )


def load_raw(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw_bytes = path.read_bytes()
        if len(raw_bytes) > MAX_STATE_BYTES:
            raise SpecError("spec exceeds the 1 MiB limit")
        raw_text = raw_bytes.decode("utf-8")
        if path.suffix.lower() == ".json":
            data = json.loads(raw_text)
        else:
            if tomllib is None:
                raise SpecError("TOML specs require Python 3.11 or newer")
            data = tomllib.loads(raw_text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpecError(f"could not read spec: {exc}") from exc
    except Exception as exc:
        if tomllib is not None and isinstance(exc, tomllib.TOMLDecodeError):
            raise SpecError(f"could not parse spec: {exc}") from exc
        raise
    if not isinstance(data, dict):
        raise SpecError("spec root must be an object")
    unknown = set(data) - TOP_KEYS
    if unknown:
        raise SpecError(f"unknown top-level fields: {sorted(unknown)}")
    return data, hashlib.sha256(raw_bytes).hexdigest()


def load_spec(path: Path, *, state_override: str | None = None) -> RunSpec:
    spec_path = path.resolve()
    raw, spec_sha256 = load_raw(spec_path)
    run = raw.get("run")
    if not isinstance(run, dict):
        raise SpecError("[run] is required")
    unknown_run = set(run) - RUN_KEYS
    if unknown_run:
        raise SpecError(f"unknown [run] fields: {sorted(unknown_run)}")
    name = run.get("name")
    if not isinstance(name, str) or not SAFE_ID.fullmatch(name):
        raise SpecError("run.name must be filesystem-safe (1-80 characters)")

    root_value = run.get("root", ".")
    if not isinstance(root_value, str) or Path(root_value).is_absolute():
        raise SpecError("run.root must be relative to the spec file")
    declared_root = (spec_path.parent / root_value).resolve()
    if not declared_root.is_dir():
        raise SpecError("run.root must resolve to an existing directory")
    root = canonical_project_root(declared_root)
    if declared_root != root:
        raise SpecError(
            f"run.root must resolve exactly to the canonical {ROOT_MARKER} directory"
        )
    state = confined(root, state_override or run.get("state", ".bounded-runner"), "run.state")
    lock_root = root / ".bounded-runner-locks"
    if overlaps(state, lock_root):
        raise SpecError("run.state must not overlap the fixed ownership-lock namespace")
    worker_budget = strict_int(
        run.get("worker_budget", max(1, os.cpu_count() or 1)),
        "run.worker_budget",
        minimum=1,
        maximum=1024,
    )
    poll_interval_s = strict_number(
        run.get("poll_interval_s", 0.1), "run.poll_interval_s", minimum=0.02, maximum=10
    )

    defaults = raw.get("defaults", {})
    if not isinstance(defaults, dict):
        raise SpecError("[defaults] must be an object")
    unknown_defaults = set(defaults) - (UNIT_KEYS - {"id", "cmd", "write_paths"})
    if unknown_defaults:
        raise SpecError(f"unknown [defaults] fields: {sorted(unknown_defaults)}")
    unit_rows = raw.get("unit")
    if not isinstance(unit_rows, list) or not unit_rows:
        raise SpecError("at least one [[unit]] is required")

    units: list[Unit] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(unit_rows):
        label = f"unit[{index}]"
        if not isinstance(row, dict):
            raise SpecError(f"{label} must be an object")
        merged = {**defaults, **row}
        unknown = set(merged) - UNIT_KEYS
        if unknown:
            raise SpecError(f"{label} has unknown fields: {sorted(unknown)}")
        unit_id = merged.get("id")
        if not isinstance(unit_id, str) or not SAFE_ID.fullmatch(unit_id):
            raise SpecError(f"{label}.id must be filesystem-safe (1-80 characters)")
        if unit_id in seen_ids:
            raise SpecError(f"duplicate unit id: {unit_id}")
        seen_ids.add(unit_id)

        command = argv(merged.get("cmd"), f"{label}.cmd")
        cwd = confined(root, merged.get("cwd", "."), f"{label}.cwd", must_exist_dir=True)
        readonly = strict_bool(merged.get("readonly", False), f"{label}.readonly")
        owns_raw = merged.get("write_paths", [])
        if not isinstance(owns_raw, list) or any(not isinstance(item, str) for item in owns_raw):
            raise SpecError(f"{label}.write_paths must be an array of relative paths")
        owned = tuple(confined(root, item, f"{label}.write_paths") for item in owns_raw)
        if readonly and owned:
            raise SpecError(f"{label} is readonly and must not declare write_paths")
        if not readonly and not owned:
            raise SpecError(f"{label} must declare write_paths or set readonly=true")
        for i, left in enumerate(owned):
            for right in owned[i + 1 :]:
                if overlaps(left, right):
                    raise SpecError(f"{label}.write_paths contains duplicate or overlapping paths")
        lock_root = root / ".bounded-runner-locks"
        if any(overlaps(state, item) or overlaps(lock_root, item) for item in owned):
            raise SpecError(f"{label}.write_paths must not overlap runner state or lock state")

        deadline_s = strict_number(
            merged.get("deadline_s"), f"{label}.deadline_s", minimum=0.05, maximum=604800
        )
        grace_s = strict_number(
            merged.get("grace_s", 5), f"{label}.grace_s", minimum=0, maximum=60
        )
        workers = strict_int(
            merged.get("workers", 1), f"{label}.workers", minimum=1, maximum=worker_budget
        )
        required = strict_bool(merged.get("required", True), f"{label}.required")

        checkpoint = None
        if merged.get("checkpoint") is not None:
            checkpoint = confined(root, merged["checkpoint"], f"{label}.checkpoint")
            if not any(path == checkpoint or path in checkpoint.parents for path in owned):
                raise SpecError(f"{label}.checkpoint must be covered by one of its owned paths")

        heartbeat_stall_s = None
        if merged.get("heartbeat_stall_s") is not None:
            heartbeat_stall_s = strict_number(
                merged["heartbeat_stall_s"],
                f"{label}.heartbeat_stall_s",
                minimum=0.05,
                maximum=deadline_s,
            )
        verify = None
        if merged.get("verify") is not None:
            verify = argv(merged["verify"], f"{label}.verify")
        verify_deadline_s = strict_number(
            merged.get("verify_deadline_s", min(300, deadline_s)),
            f"{label}.verify_deadline_s",
            minimum=0.05,
            maximum=86400,
        )
        env_raw = merged.get("env", {})
        if not isinstance(env_raw, dict):
            raise SpecError(f"{label}.env must be an object of string values")
        env: dict[str, str] = {}
        for key, value in env_raw.items():
            if not isinstance(key, str) or not SAFE_ENV.fullmatch(key):
                raise SpecError(f"{label}.env has an invalid variable name")
            if key in RESERVED_ENV:
                raise SpecError(f"{label}.env may not override runner-owned {key}")
            if not isinstance(value, str) or "\0" in value:
                raise SpecError(f"{label}.env values must be strings without NUL bytes")
            env[key] = value
        inherit_raw = merged.get("inherit_env", [])
        if (not isinstance(inherit_raw, list)
                or any(not isinstance(key, str) or not SAFE_ENV.fullmatch(key)
                       for key in inherit_raw)):
            raise SpecError(f"{label}.inherit_env must be an array of variable names")
        inherit_env = tuple(dict.fromkeys(inherit_raw))
        if any(key in RESERVED_ENV for key in inherit_env):
            raise SpecError(f"{label}.inherit_env may not name runner-owned variables")
        input_revision = merged.get("input_revision")
        if input_revision is not None and (
            not isinstance(input_revision, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", input_revision) is None
        ):
            raise SpecError(
                f"{label}.input_revision must be a non-secret opaque revision (1-128 characters)"
            )
        if inherit_env and input_revision is None:
            raise SpecError(
                f"{label}.input_revision is required when inherit_env affects resumable work"
            )
        note = merged.get("note", "")
        if not isinstance(note, str) or len(note) > 500:
            raise SpecError(f"{label}.note must be a string of at most 500 characters")

        units.append(Unit(
            id=unit_id,
            cmd=command,
            cwd=cwd,
            owns=owned,
            deadline_s=deadline_s,
            grace_s=grace_s,
            workers=workers,
            required=required,
            readonly=readonly,
            checkpoint=checkpoint,
            heartbeat_stall_s=heartbeat_stall_s,
            verify=verify,
            verify_deadline_s=verify_deadline_s,
            env=env,
            inherit_env=inherit_env,
            input_revision=input_revision,
            note=note,
        ))

    conflicts = ownership_conflicts(units)
    if conflicts:
        details = "; ".join(f"{a.id} vs {b.id}" for a, b in conflicts)
        raise SpecError(f"owned paths overlap: {details}; nothing was started")
    return RunSpec(
        name, root, state, worker_budget, poll_interval_s, tuple(units), spec_path,
        spec_sha256,
    )


def ownership_conflicts(units: list[Unit]) -> list[tuple[Unit, Unit]]:
    result: list[tuple[Unit, Unit]] = []
    for index, left in enumerate(units):
        for right in units[index + 1 :]:
            if any(overlaps(a, b) for a in left.owns for b in right.owns):
                result.append((left, right))
    return result


def unit_fingerprint(spec: RunSpec, unit: Unit) -> str:
    payload = {
        "schema": SCHEMA,
        "spec_sha256": spec.spec_sha256,
        "run": spec.name,
        "unit": unit.id,
        "cmd": unit.cmd,
        "cwd": rel(unit.cwd, spec.root),
        "write_paths": [rel(path, spec.root) for path in unit.owns],
        "deadline_s": unit.deadline_s,
        "grace_s": unit.grace_s,
        "heartbeat_stall_s": unit.heartbeat_stall_s,
        "checkpoint": rel(unit.checkpoint, spec.root) if unit.checkpoint else None,
        "verify": unit.verify,
        "verify_deadline_s": unit.verify_deadline_s,
        "workers": unit.workers,
        "required": unit.required,
        "readonly": unit.readonly,
        "env": unit.env,
        "inherit_env": unit.inherit_env,
        "input_revision": unit.input_revision,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def private_dir(path: Path) -> None:
    if path.is_symlink():
        raise StateError(f"private directory {path.name} must not be a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        if path.is_symlink() or not path.is_dir():
            raise StateError(f"private directory {path.name} is not a real directory")
        path.chmod(0o700)
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise StateError(f"could not make private directory {path.name} mode 0700") from exc
    if os.name != "nt" and mode != 0o700:
        raise StateError(f"private directory {path.name} is not mode 0700")


def _validate_private_file(path: Path) -> None:
    if path.is_symlink():
        raise StateError(f"state file {path.name} must not be a symlink")
    try:
        info = path.stat()
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise StateError(f"could not inspect state file {path.name}") from exc
    if info.st_size > MAX_STATE_BYTES:
        raise StateError(f"state file {path.name} exceeds the 1 MiB limit")
    if not stat.S_ISREG(info.st_mode):
        raise StateError(f"state file {path.name} is not a regular file")
    if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
        raise StateError(f"state file {path.name} is not private (expected mode 0600)")


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    private_dir(path.parent)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        make_private_file(tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def make_private_file(path: Path) -> None:
    try:
        path.chmod(0o600)
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise StateError(f"could not make private file {path.name} mode 0600") from exc
    if os.name != "nt" and mode != 0o600:
        raise StateError(f"private file {path.name} is not mode 0600")


def read_json(path: Path, *, missing_ok: bool = False) -> dict[str, Any] | None:
    try:
        _validate_private_file(path)
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if missing_ok:
            return None
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"unreadable state file {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise StateError(f"state file {path.name} is not an object")
    return value


def validate_unit_record(record: dict[str, Any], spec: RunSpec, unit: Unit) -> None:
    def optional_int(value: Any, *, positive: bool = False) -> bool:
        if value is None:
            return True
        return (isinstance(value, int) and not isinstance(value, bool)
                and (not positive or value > 0))

    def optional_number(value: Any) -> bool:
        return value is None or (
            isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)) and value >= 0
        )

    fingerprint = record.get("fingerprint")
    write_paths = record.get("write_paths")
    if set(record) != RECORD_KEYS:
        raise StateError(f"record {unit.id}.json has an unknown or incomplete schema")
    if (record.get("schema") != SCHEMA
            or record.get("id") != unit.id
            or record.get("run") != spec.name
            or record.get("status") not in STATUSES
            or not isinstance(record.get("reason"), str)
            or not isinstance(record.get("required"), bool)
            or isinstance(record.get("workers"), bool)
            or not isinstance(record.get("workers"), int)
            or record.get("workers", 0) < 1
            or not isinstance(write_paths, list)
            or any(not isinstance(item, str) or Path(item).is_absolute() for item in write_paths)
            or isinstance(record.get("deadline_s"), bool)
            or not isinstance(record.get("deadline_s"), (int, float))
            or record.get("deadline_s", 0) <= 0
            or not optional_int(record.get("exit_code"))
            or not optional_int(record.get("pid"), positive=True)
            or (record.get("started_at") is not None
                and not isinstance(record.get("started_at"), str))
            or not isinstance(record.get("ended_at"), str)
            or not optional_number(record.get("duration_s"))
            or isinstance(record.get("attempt"), bool)
            or not isinstance(record.get("attempt"), int)
            or record.get("attempt", 0) < 1
            or (record.get("checkpoint") is not None
                and not isinstance(record.get("checkpoint"), str))
            or not isinstance(record.get("checkpoint_complete"), bool)
            or not isinstance(record.get("checkpoint_state"), str)
            or (record.get("log") is not None and not isinstance(record.get("log"), str))
            or not isinstance(fingerprint, str)
            or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None
            or not isinstance(record.get("invocation"), str)
            or re.fullmatch(r"[0-9a-f]{32}", record.get("invocation", "")) is None
            or record.get("evidence") not in {"pending", "execution", "prior-ok", "checkpoint"}):
        raise StateError(f"record {unit.id}.json is malformed")


def positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def checkpoint_state(path: Path | None, expected_fingerprint: str) -> tuple[bool, str]:
    if path is None:
        return False, "not configured"
    try:
        if path.stat().st_size > MAX_STATE_BYTES:
            return False, "exceeds the 1 MiB limit"
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False, "missing"
    except (OSError, json.JSONDecodeError):
        return False, "unreadable or partial"
    if not isinstance(value, dict):
        return False, "not an object"
    if value.get("runner_fingerprint") != expected_fingerprint:
        return False, "fingerprint missing or stale"
    if value.get("done") is True:
        return True, "done=true"
    done = value.get("chunks_done")
    total = value.get("chunks_total")
    if (isinstance(done, int) and not isinstance(done, bool)
            and isinstance(total, int) and not isinstance(total, bool)
            and total > 0 and done >= total):
        return True, f"chunks {done}/{total}"
    return False, "incomplete"


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def group_alive(pgid: int) -> bool:
    if os.name == "nt":
        return pid_alive(pgid)
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True


def terminate_group(pgid: int, grace_s: float) -> bool:
    if pgid <= 0:
        return False
    if os.name == "nt":
        return False
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline and group_alive(pgid):
        time.sleep(0.02)
    if group_alive(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            return False
    # The owning caller must reap its direct Popen child before the final
    # group_alive proof; checking here would mistake that unreaped zombie for a
    # surviving process and burn an extra second past the declared grace.
    return True


class LockRegistry:
    def __init__(self, spec: RunSpec, instance: str):
        self.spec = spec
        self.instance = instance
        self.root = spec.lock_root
        self.mutex = self.root / ".mutex"
        self.path = self.root / f"{instance}.json"
        private_dir(self.root)

    def _mutex_stale(self) -> bool:
        owner_path = self.mutex / "owner.json"
        try:
            owner = read_json(owner_path)
        except FileNotFoundError:
            return False
        except StateError:
            return False
        if owner is None or not isinstance(owner.get("host"), str):
            return False
        pid = positive_int(owner.get("pid"))
        return owner.get("host") == HOST and pid is not None and not pid_alive(pid)

    @contextmanager
    def locked(self, timeout_s: float = 10) -> Iterator[None]:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                self.mutex.mkdir(mode=0o700)
                atomic_json(self.mutex / "owner.json", {"host": HOST, "pid": os.getpid()})
                break
            except FileExistsError:
                if self._mutex_stale():
                    stale = self.root / f".stale-mutex-{uuid.uuid4().hex}"
                    try:
                        self.mutex.rename(stale)
                        shutil.rmtree(stale)
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise StateError("lock registry mutex is busy or belongs to another host")
                time.sleep(0.05)
        try:
            yield
        finally:
            shutil.rmtree(self.mutex, ignore_errors=True)

    def _records(self) -> list[tuple[Path, dict[str, Any]]]:
        records: list[tuple[Path, dict[str, Any]]] = []
        for path in self.root.glob("*.json"):
            try:
                raw = read_json(path)
            except (OSError, StateError) as exc:
                raise StateError(f"malformed path lock {path.name}; refusing admission") from exc
            if raw is None:
                raise StateError(f"malformed path lock {path.name}; refusing admission")
            required = {"schema", "instance", "run", "unit", "host", "runner_pid", "child_pid",
                        "owns", "started_at"}
            if set(raw) != required or raw.get("schema") != SCHEMA:
                raise StateError(f"malformed path lock {path.name}; refusing admission")
            if (not isinstance(raw.get("instance"), str)
                    or not isinstance(raw.get("run"), str)
                    or not isinstance(raw.get("unit"), str)
                    or not isinstance(raw.get("host"), str)
                    or positive_int(raw.get("runner_pid")) is None
                    or (raw.get("child_pid") is not None
                        and positive_int(raw.get("child_pid")) is None)
                    or not isinstance(raw.get("started_at"), str)
                    or not isinstance(raw.get("owns"), list)):
                raise StateError(f"malformed path lock {path.name}; refusing admission")
            normalized: list[str] = []
            for item in raw["owns"]:
                if not isinstance(item, str):
                    raise StateError(f"malformed path lock {path.name}; refusing admission")
                candidate = Path(item)
                if not candidate.is_absolute() or candidate != candidate.resolve():
                    raise StateError(f"malformed path lock {path.name}; refusing admission")
                try:
                    candidate.relative_to(self.spec.root)
                except ValueError as exc:
                    raise StateError(
                        f"malformed path lock {path.name}; refusing admission"
                    ) from exc
                normalized.append(item)
            raw["owns"] = normalized
            records.append((path, raw))
        return records

    def acquire(self, unit: Unit, wait_s: float) -> tuple[bool, str, list[str]]:
        deadline = time.monotonic() + wait_s
        while True:
            with self.locked():
                blockers: list[dict[str, Any]] = []
                for _path, record in self._records():
                    if record.get("instance") == self.instance:
                        continue
                    theirs = [Path(item) for item in record["owns"]]
                    same_identity = (
                        record.get("run") == self.spec.name and record.get("unit") == unit.id
                    )
                    if same_identity or any(
                        overlaps(ours, theirs_path) for ours in unit.owns for theirs_path in theirs
                    ):
                        blockers.append(record)
                if not blockers:
                    atomic_json(self.path, {
                        "schema": SCHEMA,
                        "instance": self.instance,
                        "run": self.spec.name,
                        "unit": unit.id,
                        "host": HOST,
                        "runner_pid": os.getpid(),
                        "child_pid": None,
                        "owns": [str(item) for item in unit.owns],
                        "started_at": now_iso(),
                    })
                    return True, "", []
                first = blockers[0]
                blocker_pid = positive_int(first.get("runner_pid"))
                stale = (
                    first.get("host") == HOST
                    and blocker_pid is not None
                    and not pid_alive(blocker_pid)
                )
                state = "stale/unverifiable" if stale else "live or foreign-host"
                reason = (
                    f"{state} ownership lock held by run={first.get('run', '?')} "
                    f"unit={first.get('unit', '?')}; remove only after proving its process tree stopped"
                )
            if time.monotonic() >= deadline:
                return False, reason, []
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))

    def set_child(self, child_pid: int) -> None:
        with self.locked():
            record = read_json(self.path)
            assert record is not None
            record["child_pid"] = child_pid
            atomic_json(self.path, record)

    def release(self) -> None:
        with self.locked():
            self.path.unlink(missing_ok=True)


class RunLease:
    """Prevent two invocations from writing one run's canonical records."""

    def __init__(self, spec: RunSpec):
        self.root = spec.lock_root / "runs"
        self.path = self.root / spec.name
        self.owner = self.path / "owner.json"
        self.acquired = False

    def acquire(self) -> None:
        private_dir(self.root.parent)
        private_dir(self.root)
        try:
            self.path.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise StateError(
                f"run lease for {self.path.name} already exists; remove it only after proving "
                "the earlier runner and every child process stopped"
            ) from exc
        try:
            atomic_json(self.owner, {"schema": SCHEMA, "host": HOST, "pid": os.getpid()})
        except Exception:
            shutil.rmtree(self.path, ignore_errors=True)
            raise
        self.acquired = True

    def release(self) -> None:
        if not self.acquired:
            return
        owner = read_json(self.owner)
        if (owner is None or set(owner) != {"schema", "host", "pid"}
                or owner.get("schema") != SCHEMA
                or owner.get("host") != HOST
                or owner.get("pid") != os.getpid()):
            raise StateError("run lease ownership changed; refusing to remove it")
        shutil.rmtree(self.path)
        self.acquired = False


class Runner:
    def __init__(self, spec: RunSpec, *, resume: bool, wait_for_locks_s: float, quiet: bool):
        self.spec = spec
        self.resume = resume
        self.wait_for_locks_s = wait_for_locks_s
        self.quiet = quiet
        self.stop = threading.Event()
        self._previous_handlers: dict[int, Any] = {}
        self.invocation = uuid.uuid4().hex
        self._prior_records: dict[str, dict[str, Any]] = {}
        self._attempts: dict[str, int] = {}

    def say(self, message: str) -> None:
        if not self.quiet:
            print(message, flush=True)

    def _signal(self, _signum: int, _frame: Any) -> None:
        self.stop.set()

    def _install_signals(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, self._signal)

    def _restore_signals(self) -> None:
        for signum, handler in self._previous_handlers.items():
            signal.signal(signum, handler)

    def _prepare_state(self) -> None:
        private_dir(self.spec.state)
        private_dir(self.spec.state / "runs")
        private_dir(self.spec.run_dir)
        private_dir(self.spec.units_dir)
        private_dir(self.spec.logs_dir)
        private_dir(self.spec.heartbeats_dir)
        for unit in self.spec.units:
            path = self.spec.units_dir / f"{unit.id}.json"
            if path.exists():
                record = read_json(path)
                if record is None:
                    raise StateError(f"record {path.name} disappeared while being inspected")
                validate_unit_record(record, self.spec, unit)
                self._prior_records[unit.id] = record
                self._attempts[unit.id] = int(record["attempt"]) + 1
            else:
                self._attempts[unit.id] = 1
        # Invalidate every earlier terminal result before admission. A hard crash
        # can therefore leave only PENDING, never a stale success for this invocation.
        for unit in self.spec.units:
            self._write_record(
                unit, PENDING, "current invocation has not reached admission",
                started_at=None, duration_s=0, exit_code=None, log_path=None,
                evidence="pending",
            )

    def run(self) -> int:
        if os.name == "nt":
            raise StateError(
                "execution requires POSIX process-group semantics in v1; on Windows, run this "
                "command inside the project's Linux development container"
            )
        lease = RunLease(self.spec)
        lease.acquire()
        try:
            self._prepare_state()
            self._install_signals()
            pending = list(self.spec.units)
            active: dict[Future[dict[str, Any]], int] = {}
            available = self.spec.worker_budget
            self.say(f"run {self.spec.name}: worker budget {available}, {len(pending)} unit(s)")
            try:
                with ThreadPoolExecutor(
                    max_workers=len(pending), thread_name_prefix="bounded-unit"
                ) as pool:
                    while pending or active:
                        while (pending and not self.stop.is_set()
                               and pending[0].workers <= available):
                            unit = pending.pop(0)
                            available -= unit.workers
                            future = pool.submit(self._run_unit, unit)
                            active[future] = unit.workers
                        if not active:
                            if self.stop.is_set():
                                break
                            raise StateError("scheduler made no progress")
                        done, _ = wait(
                            active, timeout=self.spec.poll_interval_s,
                            return_when=FIRST_COMPLETED,
                        )
                        for future in done:
                            available += active.pop(future)
                            future.result()
                    if self.stop.is_set():
                        for unit in pending:
                            self._write_record(
                                unit, KILLED, "runner received an interrupt before admission",
                                started_at=None, duration_s=0, exit_code=None, log_path=None,
                            )
                        self.say("runner interrupted; unstarted units recorded KILLED")
            finally:
                self._restore_signals()
            return aggregate(
                self.spec, verbose=not self.quiet, as_json=False, write_summary=True,
                ignore_run_lease=True,
            )
        finally:
            lease.release()

    def _record_path(self, unit: Unit) -> Path:
        return self.spec.units_dir / f"{unit.id}.json"

    def _write_record(self, unit: Unit, status: str, reason: str, *, started_at: str | None,
                      duration_s: float | None, exit_code: int | None, log_path: Path | None,
                      pid: int | None = None, evidence: str = "execution") -> dict[str, Any]:
        attempt = self._attempts.get(unit.id)
        if attempt is None:
            raise StateError(f"attempt counter for {unit.id} was not prepared")
        fingerprint = unit_fingerprint(self.spec, unit)
        complete, checkpoint_reason = checkpoint_state(unit.checkpoint, fingerprint)
        record: dict[str, Any] = {
            "schema": SCHEMA,
            "id": unit.id,
            "run": self.spec.name,
            "status": status,
            "reason": reason,
            "required": unit.required,
            "workers": unit.workers,
            "write_paths": [rel(path, self.spec.root) for path in unit.owns],
            "deadline_s": unit.deadline_s,
            "exit_code": exit_code,
            "pid": pid,
            "started_at": started_at,
            "ended_at": now_iso(),
            "duration_s": round(duration_s, 3) if duration_s is not None else None,
            "attempt": attempt,
            "checkpoint": rel(unit.checkpoint, self.spec.root) if unit.checkpoint else None,
            "checkpoint_complete": complete,
            "checkpoint_state": checkpoint_reason,
            "log": rel(log_path, self.spec.root) if log_path else None,
            "fingerprint": fingerprint,
            "invocation": self.invocation,
            "evidence": evidence,
        }
        atomic_json(self._record_path(unit), record)
        self.say(f"[{status.lower():7}] {unit.id}: {reason}")
        return record

    def _run_unit(self, unit: Unit) -> dict[str, Any]:
        prior = self._prior_records.get(unit.id)
        fingerprint = unit_fingerprint(self.spec, unit)
        complete, checkpoint_reason = checkpoint_state(unit.checkpoint, fingerprint)
        if (self.resume and prior and prior.get("status") == OK
                and prior.get("fingerprint") == fingerprint):
            return self._write_record(
                unit, SKIPPED, "prior OK record with exact fingerprint",
                started_at=None,
                duration_s=0, exit_code=0, log_path=None, evidence="prior-ok",
            )
        if self.resume and complete:
            return self._write_record(
                unit, SKIPPED, f"checkpoint complete ({checkpoint_reason})", started_at=None,
                duration_s=0, exit_code=0, log_path=None, evidence="checkpoint",
            )

        missing_env = [key for key in unit.inherit_env if key not in os.environ]
        if missing_env:
            return self._write_record(
                unit, FAIL, "required inherited environment variable is missing",
                started_at=None, duration_s=0, exit_code=None, log_path=None,
            )

        instance = f"{self.spec.name}-{unit.id}-{os.getpid()}-{uuid.uuid4().hex}"
        registry = LockRegistry(self.spec, instance)
        try:
            acquired, blocked_reason, notes = registry.acquire(unit, self.wait_for_locks_s)
        except (OSError, StateError) as exc:
            return self._write_record(
                unit, BLOCKED, "ownership registry is unreadable; refusing admission",
                started_at=None, duration_s=0, exit_code=None, log_path=None,
            )
        if not acquired:
            return self._write_record(
                unit, BLOCKED, blocked_reason, started_at=None, duration_s=0,
                exit_code=None, log_path=None,
            )

        log_path = self.spec.logs_dir / f"{unit.id}-{uuid.uuid4().hex}.log"
        heartbeat_path = self.spec.heartbeats_dir / f"{unit.id}-{uuid.uuid4().hex}"
        log_fd: int | None = None
        try:
            heartbeat_fd = os.open(heartbeat_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(heartbeat_fd)
            make_private_file(heartbeat_path)
            log_fd = os.open(log_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            make_private_file(log_path)
            env = {key: value for key, value in os.environ.items() if key in BASE_ENV}
            env.update({key: os.environ[key] for key in unit.inherit_env})
            env.update(unit.env)
        except (KeyError, OSError, StateError):
            if log_fd is not None:
                try:
                    os.close(log_fd)
                except OSError:
                    pass
            reason = "could not prepare private attempt state"
            try:
                registry.release()
            except (OSError, StateError):
                reason += "; ownership lock release failed and must be checked manually"
            return self._write_record(
                unit, FAIL, reason, started_at=None, duration_s=0,
                exit_code=None, log_path=None,
            )
        started_mono = time.monotonic()
        unit_deadline_at = started_mono + unit.deadline_s
        started_at = now_iso()
        env.update({
            "RUNNER_RUN": self.spec.name,
            "RUNNER_UNIT_ID": unit.id,
            "RUNNER_DEADLINE_S": str(unit.deadline_s),
            "RUNNER_HEARTBEAT": str(heartbeat_path),
            "RUNNER_FINGERPRINT": fingerprint,
        })
        if unit.checkpoint:
            env["RUNNER_CHECKPOINT"] = str(unit.checkpoint)
        status = FAIL
        reason = "could not start"
        exit_code: int | None = None
        child_pid: int | None = None
        release_lock = True
        try:
            assert log_fd is not None
            with os.fdopen(log_fd, "wb", buffering=0) as log:
                try:
                    kwargs: dict[str, Any] = {}
                    if os.name == "nt":
                        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                    else:
                        kwargs["start_new_session"] = True
                    process = subprocess.Popen(
                        unit.cmd, cwd=unit.cwd, env=env, stdin=subprocess.DEVNULL,
                        stdout=log, stderr=subprocess.STDOUT, shell=False, **kwargs,
                    )
                    child_pid = process.pid
                    try:
                        registry.set_child(process.pid)
                    except (OSError, StateError):
                        terminate_group(process.pid, unit.grace_s)
                        try:
                            process.wait(timeout=max(1, unit.grace_s + 1))
                        except subprocess.TimeoutExpired:
                            terminate_group(process.pid, 0)
                        status = FAIL
                        reason = "could not bind the child to its ownership lock"
                        if group_alive(process.pid):
                            reason += "; process-tree cleanup unproven; ownership lock retained"
                            release_lock = False
                        process = None
                except OSError as exc:
                    reason = f"command could not start: {exc.__class__.__name__}"
                    process = None

                while process is not None and process.poll() is None:
                    elapsed = time.monotonic() - started_mono
                    if self.stop.is_set():
                        terminate_group(process.pid, unit.grace_s)
                        status, reason = KILLED, "runner received an interrupt; process group terminated"
                        break
                    if elapsed >= unit.deadline_s:
                        terminate_group(process.pid, unit.grace_s)
                        status = TIMEOUT
                        reason = f"exceeded deadline_s={unit.deadline_s:g}; process group terminated"
                        break
                    if unit.heartbeat_stall_s is not None:
                        try:
                            heartbeat_age = time.time() - heartbeat_path.stat().st_mtime
                        except OSError:
                            heartbeat_age = unit.heartbeat_stall_s + 1
                        if heartbeat_age >= unit.heartbeat_stall_s:
                            terminate_group(process.pid, unit.grace_s)
                            status = STALLED
                            reason = (
                                f"heartbeat stale for {heartbeat_age:.2f}s "
                                f"(limit {unit.heartbeat_stall_s:g}s); process group terminated"
                            )
                            break
                    time.sleep(self.spec.poll_interval_s)

                if process is not None:
                    try:
                        exit_code = process.wait(timeout=max(1, unit.grace_s + 1))
                    except subprocess.TimeoutExpired:
                        terminate_group(process.pid, 0)
                        exit_code = process.poll()
                    if status not in {TIMEOUT, STALLED, KILLED}:
                        status = OK if exit_code == 0 else FAIL
                        reason = "command exited 0" if exit_code == 0 else f"command exited {exit_code}"
                    surviving_descendants = group_alive(process.pid)
                    if surviving_descendants:
                        terminate_group(process.pid, min(1, unit.grace_s))
                        status = FAIL
                        reason = "command exited with surviving process-group members; terminated"
                        if group_alive(process.pid):
                            reason += "; cleanup unproven; ownership lock retained"
                            release_lock = False

                if status == OK and unit.verify:
                    verify_status, verify_reason, verify_cleanup = self._verify(
                        unit, env, log, registry, unit_deadline_at
                    )
                    status = verify_status
                    reason = verify_reason
                    if not verify_cleanup:
                        reason += "; ownership lock retained"
                        release_lock = False
                if notes:
                    reason += "; " + "; ".join(notes)
        finally:
            if release_lock:
                try:
                    registry.release()
                except (OSError, StateError):
                    status = FAIL
                    reason += "; ownership lock release failed and must be checked manually"
        return self._write_record(
            unit, status, reason, started_at=started_at,
            duration_s=time.monotonic() - started_mono, exit_code=exit_code,
            log_path=log_path, pid=child_pid,
        )

    def _verify(self, unit: Unit, env: dict[str, str], log: Any, registry: LockRegistry,
                unit_deadline_at: float) -> tuple[str, str, bool]:
        assert unit.verify is not None
        if self.stop.is_set():
            return KILLED, "runner received an interrupt before verification", True
        if time.monotonic() >= unit_deadline_at:
            return TIMEOUT, f"exceeded deadline_s={unit.deadline_s:g} before verification", True
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(
                unit.verify, cwd=unit.cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, shell=False, **kwargs,
            )
        except OSError as exc:
            return FAIL, f"verify could not start: {exc.__class__.__name__}", True
        try:
            registry.set_child(process.pid)
        except (OSError, StateError):
            terminate_group(process.pid, unit.grace_s)
            try:
                process.wait(timeout=max(1, unit.grace_s + 1))
            except subprocess.TimeoutExpired:
                terminate_group(process.pid, 0)
            cleanup = not group_alive(process.pid)
            return FAIL, "could not bind verification to its ownership lock", cleanup

        verify_started = time.monotonic()
        verify_deadline_at = min(
            unit_deadline_at, verify_started + unit.verify_deadline_s
        )
        timeout_reason = ""
        timeout_status = TIMEOUT
        while process.poll() is None:
            current = time.monotonic()
            if self.stop.is_set():
                timeout_status = KILLED
                timeout_reason = "runner received an interrupt during verification"
                break
            if current >= unit_deadline_at:
                timeout_reason = f"exceeded deadline_s={unit.deadline_s:g} during verification"
                break
            if current >= verify_deadline_at:
                timeout_reason = (
                    f"verify exceeded verify_deadline_s={unit.verify_deadline_s:g}"
                )
                break
            time.sleep(min(self.spec.poll_interval_s, max(0, verify_deadline_at - current)))

        if timeout_reason:
            terminate_group(process.pid, unit.grace_s)
            try:
                process.wait(timeout=max(1, unit.grace_s + 1))
            except subprocess.TimeoutExpired:
                terminate_group(process.pid, 0)
            if group_alive(process.pid):
                return timeout_status, timeout_reason + "; process-tree cleanup is unproven", False
            return timeout_status, timeout_reason, True

        code = process.wait()
        surviving_descendants = group_alive(process.pid)
        if surviving_descendants:
            terminate_group(process.pid, min(1, unit.grace_s))
            if group_alive(process.pid):
                return FAIL, "verify exited with surviving process-group members; cleanup unproven", False
            return FAIL, "verify exited with surviving process-group members; terminated", True
        return ((OK, "command and verification exited 0", True) if code == 0
                else (FAIL, f"verify exited {code}", True))


def aggregate(spec: RunSpec, *, verbose: bool, as_json: bool, write_summary: bool,
              ignore_run_lease: bool = False) -> int:
    records: list[dict[str, Any]] = []
    for unit in spec.units:
        record = read_json(spec.units_dir / f"{unit.id}.json", missing_ok=True)
        fingerprint = unit_fingerprint(spec, unit)
        if record is not None:
            validate_unit_record(record, spec, unit)
        if record is not None and (
            record.get("schema") != SCHEMA
            or record.get("id") != unit.id
            or record.get("fingerprint") != fingerprint
        ):
            record = None
        if record is None:
            record = {
                "schema": SCHEMA, "id": unit.id, "run": spec.name, "status": MISSING,
                "reason": "declared unit has no record; silence is not success",
                "required": unit.required,
                "write_paths": [rel(path, spec.root) for path in unit.owns],
                "fingerprint": fingerprint,
            }
        records.append(record)
    counts: dict[str, int] = {}
    for record in records:
        status = str(record.get("status", MISSING))
        counts[status] = counts.get(status, 0) + 1
    incomplete = [
        str(record.get("id")) for record in records
        if (record.get("status") in {MISSING, PENDING}
            or (record.get("required", True) and record.get("status") not in GOOD))
    ]
    lease_path = spec.lock_root / "runs" / spec.name
    run_lease_present = (lease_path.exists() or lease_path.is_symlink()) and not ignore_run_lease
    if run_lease_present:
        incomplete.append("<active-or-stale-run-lease>")
    summary = {
        "schema": SCHEMA,
        "coverage": {
            "run": spec.name, "declared": len(spec.units),
            "recorded": sum(record.get("status") != MISSING for record in records),
            "counts": counts, "required_incomplete": incomplete,
            "run_lease_present": run_lease_present,
            "exit_code": 1 if incomplete else 0, "generated_at": now_iso(),
        },
        "units": records,
    }
    if write_summary:
        atomic_json(spec.run_dir / "run.json", summary)
    if as_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    elif verbose:
        for record in records:
            print(f"{record.get('status', MISSING):<8} {record.get('id')}: {record.get('reason', '')}")
        print(f"coverage {summary['coverage']['recorded']}/{summary['coverage']['declared']}")
        if incomplete:
            print("required incomplete: " + ", ".join(incomplete))
    return int(summary["coverage"]["exit_code"])


def preflight(spec: RunSpec) -> int:
    print(f"run: {spec.name}")
    print(f"root: {spec.root}")
    print(f"state: {spec.state}")
    print(f"worker budget: {spec.worker_budget}")
    for unit in spec.units:
        heartbeat = f", heartbeat {unit.heartbeat_stall_s:g}s" if unit.heartbeat_stall_s else ""
        print(f"  {unit.id}: {unit.workers} worker(s), deadline {unit.deadline_s:g}s{heartbeat}")
        for path in unit.owns:
            print(f"    owns {rel(path, spec.root)}")
    print(f"preflight OK: {len(spec.units)} unit(s), no ownership conflicts; nothing started")
    return 0


def main(argv_in: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="bounded, partitioned, resumable unit runner")
    parser.add_argument("command", choices=("preflight", "run", "aggregate", "status"))
    parser.add_argument("spec", type=Path)
    parser.add_argument("--state", help="override state path (still confined under run.root)")
    parser.add_argument(
        "--resume", action="store_true",
        help="reuse only exact fingerprint-bound success/checkpoint evidence",
    )
    parser.add_argument("--wait-for-locks", type=float, default=0, metavar="SECONDS")
    parser.add_argument("--json", action="store_true", help="machine-readable aggregate output")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv_in)
    if (not math.isfinite(args.wait_for_locks)
            or args.wait_for_locks < 0 or args.wait_for_locks > 86400):
        parser.error("--wait-for-locks must be between 0 and 86400")
    try:
        spec = load_spec(args.spec, state_override=args.state)
        if args.command == "preflight":
            return preflight(spec)
        if args.command == "aggregate":
            return aggregate(
                spec, verbose=not args.quiet, as_json=args.json, write_summary=True
            )
        if args.command == "status":
            return aggregate(
                spec, verbose=not args.quiet, as_json=args.json, write_summary=False
            )
        return Runner(spec, resume=args.resume, wait_for_locks_s=args.wait_for_locks,
                      quiet=args.quiet).run()
    except SpecError as exc:
        print(f"{exc.__class__.__name__.upper()}: {exc}", file=sys.stderr)
        return 2
    except StateError as exc:
        print(f"{exc.__class__.__name__.upper()}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
