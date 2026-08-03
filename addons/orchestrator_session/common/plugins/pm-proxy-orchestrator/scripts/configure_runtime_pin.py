#!/usr/bin/env python3
"""Pin the exact local Firestarter runtime bundle for MCP control calls.

This is an owner-operated bootstrap command, not an MCP tool.  It writes one
owner-private content pin beneath ``~/.codex/orchestrator-state``.  The MCP
server revalidates that pin before every typed operation and fails closed if
the selected worktree, control version, schemas, guard, or verifier drift.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from mcp_server import (
    McpError,
    RUNTIME_PIN_NAME,
    RUNTIME_PIN_VERSION,
    SERVER_VERSION,
    UTC,
    firestarter_cli,
    private_root,
    project_candidate,
    runtime_bundle_digest,
)


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def pin_value(project: Path, configured_at: str) -> dict[str, Any]:
    control_root = firestarter_cli(project).parent
    control_version = (control_root / "VERSION").read_text(
        encoding="utf-8"
    ).strip()
    return {
        "pin_version": RUNTIME_PIN_VERSION,
        "plugin_version": SERVER_VERSION,
        "project_root": str(project),
        "control_version": control_version,
        "runtime_sha256": runtime_bundle_digest(project),
        "configured_at": configured_at,
    }


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    if path.exists() and (not path.is_file() or path.is_symlink()):
        raise ValueError("runtime pin target is not a regular file")
    descriptor, name = tempfile.mkstemp(
        prefix=".runtime-pin-", suffix=".json", dir=path.parent
    )
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(
                value,
                handle,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--now", default=None)
    args = parser.parse_args()
    try:
        project = project_candidate(args.project_root)
        configured_at = args.now or utc_now()
        if UTC.fullmatch(configured_at) is None:
            raise McpError("invalid-now")
        value = pin_value(project, configured_at)
        path = private_root() / RUNTIME_PIN_NAME
        atomic_write(path, value)
    except (McpError, OSError, UnicodeDecodeError, ValueError) as exc:
        code = str(exc) if isinstance(exc, McpError) else "runtime-pin-configuration-failed"
        print(
            json.dumps(
                {
                    "ok": False,
                    "operation": "configure-runtime-pin",
                    "error": {"code": code},
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "operation": "configure-runtime-pin",
                "result": value,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
