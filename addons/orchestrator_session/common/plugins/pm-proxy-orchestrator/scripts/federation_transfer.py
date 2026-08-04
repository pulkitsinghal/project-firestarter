#!/usr/bin/env python3
"""Owner-operated two-phase ORC leadership transfer.

This coordinator is intentionally not an MCP tool. It drives only the six
closed authority-transfer commands in the pinned Firestarter CLI and requires
each source Desktop host to be disarmed before either old root is demoted.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


OPAQUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
MAX_BYTES = 2_000_000


class TransferError(ValueError):
    pass


def private_directory(value: str, label: str) -> Path:
    raw = Path(value)
    if not raw.is_absolute() or raw.is_symlink():
        raise TransferError(f"{label}-invalid")
    try:
        path = raw.resolve(strict=True)
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise TransferError(f"{label}-invalid") from exc
    if not path.is_dir() or mode != 0o700:
        raise TransferError(f"{label}-not-private")
    return path


def control_cli(value: str) -> Path:
    raw = Path(value)
    if not raw.is_absolute() or raw.is_symlink():
        raise TransferError("control-cli-invalid")
    try:
        path = raw.resolve(strict=True)
    except OSError as exc:
        raise TransferError("control-cli-invalid") from exc
    if not path.is_file() or path.name != "orchestrator_control.py":
        raise TransferError("control-cli-invalid")
    return path


def opaque(value: str, label: str) -> str:
    if OPAQUE.fullmatch(value) is None:
        raise TransferError(f"{label}-invalid")
    return value


def invoke(cli: Path, state: Path, command: str, request: dict[str, Any] | None = None) -> dict[str, Any]:
    arguments = [
        sys.executable,
        "-B",
        str(cli),
        "--state-dir",
        str(state),
        command,
    ]
    payload = None
    if request is not None:
        arguments.extend(["--request", "-"])
        payload = json.dumps(request, sort_keys=True, separators=(",", ":"))
    completed = subprocess.run(
        arguments,
        input=payload,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
        env={
            "HOME": str(Path.home()),
            "LANG": "C.UTF-8",
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
    )
    raw = completed.stdout if completed.returncode == 0 else completed.stderr
    if len(raw.encode("utf-8")) > MAX_BYTES:
        raise TransferError("control-response-too-large")
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TransferError("control-response-invalid") from exc
    if completed.returncode != 0 or response.get("ok") is not True:
        error = response.get("error", {})
        code = error.get("code", "CONTROL_DENIED")
        raise TransferError(str(code).lower().replace("_", "-"))
    result = response.get("result")
    if not isinstance(result, dict):
        raise TransferError("control-response-invalid")
    return result


def status(cli: Path, state: Path) -> dict[str, Any]:
    return invoke(cli, state, "status")


def request_id(transfer_id: str, step: str, authority_id: str) -> str:
    value = f"{transfer_id}\0{step}\0{authority_id}".encode("utf-8")
    return f"authority-{step}-{hashlib.sha256(value).hexdigest()[:24]}"


def step_receipt(authority: dict[str, Any], step: str) -> dict[str, Any]:
    matches = [
        item.get("receipt")
        for item in authority.get("transfer_steps", [])
        if item.get("step") == step and isinstance(item.get("receipt"), dict)
    ]
    if len(matches) != 1:
        raise TransferError(f"{step.lower()}-receipt-missing")
    return matches[0]


def disarmed_host(value: str) -> dict[str, Any]:
    host = private_directory(value, "source-host")
    session_path = host / "session.json"
    try:
        if (
            not session_path.is_file()
            or session_path.is_symlink()
            or stat.S_IMODE(session_path.stat().st_mode) != 0o600
            or session_path.stat().st_size > 128_000
        ):
            raise TransferError("source-host-session-invalid")
        session = json.loads(session_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransferError("source-host-session-invalid") from exc
    if not isinstance(session, dict) or session.get("armed") is not False:
        raise TransferError("source-host-still-armed")
    for field in ("desktop_pid", "proxy_pid", "app_server_pid"):
        pid = session.get(field)
        if pid is None:
            continue
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
            raise TransferError("source-host-session-invalid")
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        except (PermissionError, OSError) as exc:
            raise TransferError("source-host-process-unverifiable") from exc
        raise TransferError("source-host-process-still-running")
    instance_id = session.get("instance_id")
    if not isinstance(instance_id, str) or OPAQUE.fullmatch(instance_id) is None:
        raise TransferError("source-host-session-invalid")
    return {"instance_id": instance_id, "armed": False, "processes_absent": True}


def current_authority(current: dict[str, Any]) -> dict[str, Any]:
    authority = current.get("authority")
    if not isinstance(authority, dict):
        raise TransferError("authority-status-missing")
    return authority


def apply_transfer(
    *,
    cli: Path,
    target: Path,
    sources: list[Path],
    hosts: list[str],
    transfer_id: str,
    evidence_refs: list[str],
    now: str,
) -> dict[str, Any]:
    host_evidence = [disarmed_host(value) for value in hosts]
    target_status = status(cli, target)
    target_authority = current_authority(target_status)
    target_id = target_authority["authority_id"]
    if target_authority.get("active_transfer_id") not in {None, transfer_id}:
        raise TransferError("target-transfer-conflict")

    source_receipts: list[dict[str, Any]] = []
    for index, source in enumerate(sources):
        current = status(cli, source)
        authority = current_authority(current)
        if authority.get("active_transfer_id") not in {None, transfer_id}:
            raise TransferError("source-transfer-conflict")
        if authority["state"] == "ACTIVE_ROOT":
            receipt = invoke(
                cli,
                source,
                "prepare-authority-transfer",
                {
                    "interface_version": "1.0",
                    "request_id": request_id(
                        transfer_id, "prepare", authority["authority_id"]
                    ),
                    "transfer_id": transfer_id,
                    "target_authority_id": target_id,
                    "expected_state_revision": current["revision"],
                    "evidence_refs": [*evidence_refs, f"source-host-{index + 1}-disarmed"],
                    "now": now,
                },
            )
        elif authority["state"] in {
            "SOURCE_PREPARED",
            "SUBORDINATE_PENDING",
            "SUBORDINATE",
        }:
            receipt = step_receipt(authority, "SOURCE_PREPARE")
        else:
            raise TransferError("source-authority-state-invalid")
        source_receipts.append(receipt)

    target_status = status(cli, target)
    target_authority = current_authority(target_status)
    if target_authority["state"] == "ACTIVE_ROOT":
        stage = invoke(
            cli,
            target,
            "stage-federation",
            {
                "interface_version": "1.0",
                "request_id": request_id(transfer_id, "stage", target_id),
                "transfer_id": transfer_id,
                "expected_state_revision": target_status["revision"],
                "source_receipts": source_receipts,
                "evidence_refs": evidence_refs,
                "now": now,
            },
        )
    elif target_authority["state"] in {"TARGET_STAGED", "ACTIVE_FEDERATION_ROOT"}:
        stage = step_receipt(target_authority, "TARGET_STAGE")
    else:
        raise TransferError("target-authority-state-invalid")

    finalized: list[dict[str, Any]] = []
    for source in sources:
        current = status(cli, source)
        authority = current_authority(current)
        if authority["state"] == "SOURCE_PREPARED":
            receipt = invoke(
                cli,
                source,
                "finalize-authority-transfer",
                {
                    "interface_version": "1.0",
                    "request_id": request_id(
                        transfer_id, "finalize", authority["authority_id"]
                    ),
                    "transfer_id": transfer_id,
                    "target_stage_receipt": stage,
                    "now": now,
                },
            )
        elif authority["state"] in {"SUBORDINATE_PENDING", "SUBORDINATE"}:
            receipt = step_receipt(authority, "SOURCE_FINALIZE")
        else:
            raise TransferError("source-finalization-state-invalid")
        finalized.append(receipt)

    target_status = status(cli, target)
    target_authority = current_authority(target_status)
    if target_authority["state"] == "TARGET_STAGED":
        activation = invoke(
            cli,
            target,
            "activate-federation",
            {
                "interface_version": "1.0",
                "request_id": request_id(transfer_id, "activate", target_id),
                "transfer_id": transfer_id,
                "source_finalize_receipts": finalized,
                "evidence_refs": evidence_refs,
                "now": now,
            },
        )
    elif target_authority["state"] == "ACTIVE_FEDERATION_ROOT":
        activation = step_receipt(target_authority, "TARGET_ACTIVATE")
    else:
        raise TransferError("target-activation-state-invalid")

    enabled = []
    for source in sources:
        current = status(cli, source)
        authority = current_authority(current)
        if authority["state"] == "SUBORDINATE_PENDING":
            receipt = invoke(
                cli,
                source,
                "enable-subordinate",
                {
                    "interface_version": "1.0",
                    "request_id": request_id(
                        transfer_id, "enable", authority["authority_id"]
                    ),
                    "transfer_id": transfer_id,
                    "target_activation_receipt": activation,
                    "now": now,
                },
            )
        elif authority["state"] == "SUBORDINATE":
            receipt = step_receipt(authority, "SOURCE_ENABLE")
        else:
            raise TransferError("source-enable-state-invalid")
        enabled.append(receipt)

    return federation_status(
        cli=cli,
        target=target,
        sources=sources,
        transfer_id=transfer_id,
        host_evidence=host_evidence,
        applied=True,
    )


def abort_transfer(
    *, cli: Path, target: Path, sources: list[Path], transfer_id: str, now: str
) -> dict[str, Any]:
    ordered = [target, *sources]
    for state in ordered:
        current = status(cli, state)
        authority = current_authority(current)
        if authority["state"] in {
            "ACTIVE_FEDERATION_ROOT",
            "SUBORDINATE_PENDING",
            "SUBORDINATE",
        }:
            raise TransferError("transfer-is-forward-only-after-source-demotion")
        if authority["state"] in {"TARGET_STAGED", "SOURCE_PREPARED"}:
            invoke(
                cli,
                state,
                "abort-authority-transfer",
                {
                    "interface_version": "1.0",
                    "request_id": request_id(
                        transfer_id, "abort", authority["authority_id"]
                    ),
                    "transfer_id": transfer_id,
                    "expected_authority_state": authority["state"],
                    "expected_state_revision": current["revision"],
                    "target_activation_absent": True,
                    "reason_code": "OWNER_VERIFIED_ABORT",
                    "evidence_refs": ["owner-verified-target-not-active"],
                    "now": now,
                },
            )
        elif authority["state"] != "ACTIVE_ROOT":
            raise TransferError("abort-authority-state-invalid")
    return federation_status(
        cli=cli,
        target=target,
        sources=sources,
        transfer_id=transfer_id,
        host_evidence=[],
        applied=False,
    )


def federation_status(
    *,
    cli: Path,
    target: Path,
    sources: list[Path],
    transfer_id: str,
    host_evidence: list[dict[str, Any]],
    applied: bool,
) -> dict[str, Any]:
    target_status = status(cli, target)
    source_statuses = [status(cli, source) for source in sources]
    target_authority = current_authority(target_status)
    source_authorities = [current_authority(item) for item in source_statuses]
    return {
        "ok": True,
        "operation": "apply" if applied else "status",
        "transfer_id": transfer_id,
        "target": {
            "authority_id": target_authority["authority_id"],
            "state": target_authority["state"],
            "federated_configured_capacity": target_authority[
                "federated_configured_capacity"
            ],
            "local_worker_launch_allowed": target_authority[
                "local_worker_launch_allowed"
            ],
        },
        "sources": [
            {
                "authority_id": authority["authority_id"],
                "state": authority["state"],
                "parent_authority_id": authority["parent_authority_id"],
                "configured_capacity": current["worker_capacity"][
                    "configured_capacity"
                ],
            }
            for authority, current in zip(source_authorities, source_statuses)
        ],
        "source_host_evidence": host_evidence,
        "single_active_root": (
            target_authority["state"] == "ACTIVE_FEDERATION_ROOT"
            and all(authority["state"] == "SUBORDINATE" for authority in source_authorities)
        ),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--cli", required=True)
    result.add_argument("--target-state", required=True)
    result.add_argument("--source-state", action="append", required=True)
    result.add_argument("--source-host-dir", action="append", default=[])
    result.add_argument("--transfer-id", required=True)
    result.add_argument("--evidence-ref", action="append", default=[])
    result.add_argument("--now")
    result.add_argument("operation", choices=("status", "apply", "abort"))
    return result


def main() -> int:
    try:
        args = parser().parse_args()
        cli = control_cli(args.cli)
        target = private_directory(args.target_state, "target-state")
        sources = [
            private_directory(value, "source-state") for value in args.source_state
        ]
        if not 2 <= len(sources) <= 16 or len(set(sources)) != len(sources):
            raise TransferError("source-state-count-invalid")
        if target in sources:
            raise TransferError("target-cannot-be-source")
        transfer_id = opaque(args.transfer_id, "transfer-id")
        now = args.now or dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")
        if UTC.fullmatch(now) is None:
            raise TransferError("now-invalid")
        evidence_refs = args.evidence_ref or ["owner-authorized-federation"]
        evidence_refs = [opaque(value, "evidence-ref") for value in evidence_refs]
        if args.operation == "apply":
            if len(args.source_host_dir) != len(sources):
                raise TransferError("source-host-count-invalid")
            result = apply_transfer(
                cli=cli,
                target=target,
                sources=sources,
                hosts=args.source_host_dir,
                transfer_id=transfer_id,
                evidence_refs=evidence_refs,
                now=now,
            )
        elif args.operation == "abort":
            result = abort_transfer(
                cli=cli,
                target=target,
                sources=sources,
                transfer_id=transfer_id,
                now=now,
            )
        else:
            result = federation_status(
                cli=cli,
                target=target,
                sources=sources,
                transfer_id=transfer_id,
                host_evidence=[],
                applied=False,
            )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, subprocess.SubprocessError, TransferError):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "FEDERATION_TRANSFER_FAIL_CLOSED",
                        "message": "owner-operated authority transfer failed closed",
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
