#!/usr/bin/env python3
"""Resolve a root task through an owner-started desktop host adapter.

The adapter socket is a covered-path identity source, not a universal identity
claim.  A missing, malformed, or unavailable configured adapter fails closed.
When no adapter is configured the legacy project-hook activation behavior is
unchanged.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import socket
import stat
from pathlib import Path
from typing import Any


HOST_SOCKET_ENV = "ORC_DESKTOP_HOST_SOCKET"
INTERFACE_VERSION = "1.0"
MAX_MESSAGE_BYTES = 4096
SOCKET_TIMEOUT_SECONDS = 0.25
OPAQUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class HostAttestationError(RuntimeError):
    """The configured host adapter could not attest this hook event."""


def _strict_json(raw: bytes) -> dict[str, Any]:
    def no_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    if not raw or len(raw) > MAX_MESSAGE_BYTES:
        raise HostAttestationError("ROOT_HOST_ATTESTATION_INVALID")
    try:
        value = json.loads(raw, object_pairs_hook=no_duplicate)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise HostAttestationError("ROOT_HOST_ATTESTATION_INVALID") from exc
    if not isinstance(value, dict):
        raise HostAttestationError("ROOT_HOST_ATTESTATION_INVALID")
    return value


def _socket_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute() or path.is_symlink():
        raise HostAttestationError("ROOT_HOST_ATTESTATION_INVALID")
    try:
        metadata = path.stat()
        parent = path.parent.stat()
        resolved = path.resolve(strict=True)
        resolved_parent = path.parent.resolve(strict=True)
    except OSError as exc:
        raise HostAttestationError("ROOT_HOST_ATTESTATION_UNAVAILABLE") from exc
    if (
        not stat.S_ISSOCK(metadata.st_mode)
        or resolved != path
        or resolved_parent != path.parent
        or path.parent.is_symlink()
        or not stat.S_ISDIR(parent.st_mode)
        or (parent.st_mode & 0o077) != 0
        or (metadata.st_mode & 0o777) != 0o600
        or metadata.st_uid != os.getuid()
        or parent.st_uid != os.getuid()
    ):
        raise HostAttestationError("ROOT_HOST_ATTESTATION_INVALID")
    return path


def configured() -> bool:
    """Return whether this process was started by a desktop host adapter."""

    return bool(os.environ.get(HOST_SOCKET_ENV, "").strip())


def resolve(event: dict[str, Any]) -> str:
    """Return ``ROOT`` or ``WORKER`` for one exact native hook event."""

    raw_path = os.environ.get(HOST_SOCKET_ENV, "").strip()
    if not raw_path:
        return "INACTIVE"
    session_id = event.get("session_id")
    hook_event_name = event.get("hook_event_name")
    if (
        not isinstance(session_id, str)
        or OPAQUE.fullmatch(session_id) is None
        or hook_event_name not in {"PreToolUse", "PostToolUse"}
    ):
        raise HostAttestationError("ROOT_HOST_IDENTITY_INVALID")
    nonce = secrets.token_hex(16)
    request = {
        "interface_version": INTERFACE_VERSION,
        "hook_event_name": hook_event_name,
        "nonce": nonce,
        "session_id": session_id,
    }
    encoded = (
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )
    path = _socket_path(raw_path)
    response = bytearray()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(SOCKET_TIMEOUT_SECONDS)
            client.connect(str(path))
            client.sendall(encoded)
            client.shutdown(socket.SHUT_WR)
            while len(response) <= MAX_MESSAGE_BYTES:
                chunk = client.recv(1024)
                if not chunk:
                    break
                response.extend(chunk)
                if b"\n" in chunk:
                    break
    except (OSError, TimeoutError) as exc:
        raise HostAttestationError("ROOT_HOST_ATTESTATION_UNAVAILABLE") from exc
    if b"\n" not in response:
        raise HostAttestationError("ROOT_HOST_ATTESTATION_INVALID")
    payload = _strict_json(bytes(response).split(b"\n", 1)[0])
    if set(payload) != {
        "decision",
        "instance_id",
        "interface_version",
        "nonce",
        "session_id",
    }:
        raise HostAttestationError("ROOT_HOST_ATTESTATION_INVALID")
    decision = payload.get("decision")
    instance_id = payload.get("instance_id")
    if (
        payload.get("interface_version") != INTERFACE_VERSION
        or payload.get("nonce") != nonce
        or payload.get("session_id") != session_id
        or decision not in {"ROOT", "WORKER"}
        or not isinstance(instance_id, str)
        or OPAQUE.fullmatch(instance_id) is None
    ):
        raise HostAttestationError("ROOT_HOST_ATTESTATION_INVALID")
    return decision
