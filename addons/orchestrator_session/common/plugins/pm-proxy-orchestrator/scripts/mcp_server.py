#!/usr/bin/env python3
"""Local stdio MCP surface for typed Firestarter orchestration operations.

The server deliberately exposes no generic command, filesystem, or network
primitive.  Request objects are materialized only as owner-only temporary files
inside the selected private orchestrator state directory, passed to the pinned
bridge/refill programs without a shell, and removed before returning.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
BRIDGE = (
    PLUGIN_ROOT
    / "skills"
    / "pm-proxy-orchestrator"
    / "scripts"
    / "pm_proxy_bridge.py"
)
REFILL = BRIDGE.with_name("refill_saga.py")
SERVER_VERSION = "0.3.1"
MAX_MESSAGE_BYTES = 2_000_000
OPAQUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class McpError(ValueError):
    """Bounded fail-closed MCP error."""


def strict_json(raw: str) -> Any:
    def no_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise McpError("duplicate-json-key")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=no_duplicate)
    except (json.JSONDecodeError, TypeError) as exc:
        raise McpError("invalid-json") from exc


def exact_keys(
    value: Mapping[str, Any], allowed: set[str], required: set[str]
) -> None:
    if set(value) - allowed or not required.issubset(value):
        raise McpError("invalid-fields")


def opaque(value: Any, label: str) -> str:
    if not isinstance(value, str) or OPAQUE.fullmatch(value) is None:
        raise McpError(f"invalid-{label}")
    return value


def absolute_project(value: Any) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise McpError("invalid-project-root")
    root = Path(value).resolve(strict=True)
    try:
        firestarter_cli(root)
    except McpError:
        raise McpError("firestarter-cli-missing")
    return root


def firestarter_cli(project: Path) -> Path:
    candidates = (
        project / "orchestrator-control" / "orchestrator_control.py",
        project
        / "addons"
        / "orchestrator_session"
        / "common"
        / "orchestrator-control"
        / "orchestrator_control.py",
    )
    matches = [path for path in candidates if path.is_file() and not path.is_symlink()]
    if len(matches) != 1:
        raise McpError("firestarter-cli-missing")
    return matches[0]


def runtime_verifier(project: Path) -> Path:
    candidates = (
        project / "bin" / "verify-orchestrator-runtime.py",
        project
        / "addons"
        / "orchestrator_session"
        / "common"
        / "bin"
        / "verify-orchestrator-runtime.py",
    )
    matches = [path for path in candidates if path.is_file() and not path.is_symlink()]
    if len(matches) != 1:
        raise McpError("runtime-verifier-missing")
    return matches[0]


def private_state(value: Any) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise McpError("invalid-state-dir")
    path = Path(value).resolve(strict=True)
    configured_root = Path.home() / ".codex" / "orchestrator-state"
    try:
        if (
            configured_root.is_symlink()
            or (configured_root.stat().st_mode & 0o777) != 0o700
        ):
            raise McpError("state-root-not-private")
        allowed_root = configured_root.resolve(strict=True)
    except OSError as exc:
        raise McpError("state-root-not-private") from exc
    try:
        path.relative_to(allowed_root)
    except ValueError as exc:
        raise McpError("state-dir-outside-private-root") from exc
    if path.is_symlink() or (path.stat().st_mode & 0o777) != 0o700:
        raise McpError("state-dir-not-private")
    return path


def ticket_path(state: Path, ticket_id: Any, *, must_exist: bool) -> Path:
    identifier = opaque(ticket_id, "ticket-id")
    path = state / f"{identifier}.ticket.json"
    if must_exist and (not path.is_file() or path.is_symlink()):
        raise McpError("ticket-missing")
    if not must_exist and path.exists():
        raise McpError("ticket-already-exists")
    return path


@contextmanager
def request_files(
    state: Path, values: Mapping[str, Any]
) -> Iterator[dict[str, Path]]:
    request_dir = state / ".mcp-requests"
    request_dir.mkdir(mode=0o700, exist_ok=True)
    if request_dir.is_symlink() or (request_dir.stat().st_mode & 0o777) != 0o700:
        raise McpError("request-dir-not-private")
    paths: dict[str, Path] = {}
    try:
        for label, value in values.items():
            raw = json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            )
            if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
                raise McpError("request-too-large")
            descriptor, name = tempfile.mkstemp(
                prefix=f"{label}-", suffix=".json", dir=request_dir
            )
            path = Path(name)
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    descriptor = -1
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
            paths[label] = path
        yield paths
    finally:
        for path in paths.values():
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def invoke(argv: list[str], *, timeout: int = 30) -> dict[str, Any]:
    completed = subprocess.run(
        argv,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(Path.home()),
            "LANG": "C.UTF-8",
        },
    )
    raw = completed.stdout if completed.returncode == 0 else completed.stderr
    if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise McpError("control-response-too-large")
    try:
        payload = strict_json(raw)
    except McpError as exc:
        raise McpError("control-response-invalid") from exc
    if not isinstance(payload, dict):
        raise McpError("control-response-invalid")
    if completed.returncode != 0 or payload.get("ok") is not True:
        error = payload.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        if not isinstance(code, str) or OPAQUE.fullmatch(code) is None:
            code = "control-operation-denied"
        raise McpError(code.lower().replace("_", "-"))
    return payload


def bridge_base(project: Path, state: Path) -> list[str]:
    return [
        sys.executable,
        str(BRIDGE),
        "--cli",
        str(firestarter_cli(project)),
        "--state-dir",
        str(state),
    ]


def root_guard(
    project: Path,
    state: Path,
    action_type: str,
    *,
    evidence: list[dict[str, Any]] | None = None,
) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    token = uuid.uuid4().hex
    request = {
        "interface_version": "1.0",
        "request_id": f"mcp-{token}",
        "action_id": f"mcp-{token}",
        "action_type": action_type,
        "delegable_worker_available": True,
        "evidence": evidence or [],
        "now": now,
    }
    with request_files(state, {"root-action": request}) as paths:
        result = invoke(
            bridge_base(project, state)
            + ["root-action", "--request", str(paths["root-action"])]
        )
    decision = result.get("result", {}).get("decision")
    if decision != "ALLOW":
        raise McpError("root-action-denied")


def common(arguments: Mapping[str, Any]) -> tuple[Path, Path]:
    project = absolute_project(arguments.get("project_root"))
    state = private_state(arguments.get("state_dir"))
    return project, state


def control_call(name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    if name == "pm_proxy_verify_runtime":
        exact_keys(
            arguments,
            {"project_root", "runtime_attestation"},
            {"project_root", "runtime_attestation"},
        )
        project = absolute_project(arguments["project_root"])
        state_root = (Path.home() / ".codex" / "orchestrator-state").resolve(
            strict=True
        )
        with request_files(
            state_root, {"runtime-attestation": arguments["runtime_attestation"]}
        ) as paths:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(runtime_verifier(project)),
                    "--project-root",
                    str(project),
                    "--runtime-attestation",
                    str(paths["runtime-attestation"]),
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
        raw = completed.stdout if completed.returncode == 0 else completed.stderr
        payload = strict_json(raw)
        if completed.returncode != 0 or not isinstance(payload, dict) or payload.get("ok") is not True:
            raise McpError("runtime-verification-failed")
        return payload

    project, state = common(arguments)
    base = bridge_base(project, state)

    if name == "pm_proxy_doctor":
        exact_keys(arguments, {"project_root", "state_dir"}, {"project_root", "state_dir"})
        return invoke(base + ["doctor"])
    if name == "pm_proxy_status":
        exact_keys(arguments, {"project_root", "state_dir"}, {"project_root", "state_dir"})
        root_guard(project, state, "monitor_receipt")
        return invoke(base + ["status"])
    if name == "pm_proxy_record_dispatcher_adoption":
        exact_keys(
            arguments,
            {"project_root", "state_dir", "request"},
            {"project_root", "state_dir", "request"},
        )
        root_guard(project, state, "receive_owner_intent")
        with request_files(state, {"adoption": arguments["request"]}) as paths:
            return invoke(
                base
                + [
                    "record-dispatcher-adoption",
                    "--request",
                    str(paths["adoption"]),
                ]
            )
    if name == "pm_proxy_prepare_launch":
        exact_keys(
            arguments,
            {"project_root", "state_dir", "ticket_id", "recycle_request", "launch_request"},
            {"project_root", "state_dir", "ticket_id", "recycle_request", "launch_request"},
        )
        root_guard(project, state, "prepare_visible_task")
        ticket = ticket_path(state, arguments["ticket_id"], must_exist=False)
        with request_files(
            state,
            {
                "recycle": arguments["recycle_request"],
                "launch": arguments["launch_request"],
            },
        ) as paths:
            return invoke(
                base
                + [
                    "prepare-launch",
                    "--recycle-request",
                    str(paths["recycle"]),
                    "--launch-request",
                    str(paths["launch"]),
                    "--ticket",
                    str(ticket),
                ]
            )
    if name == "pm_proxy_record_launch_receipt":
        exact_keys(
            arguments,
            {"project_root", "state_dir", "ticket_id", "external_thread_id", "runtime_attestation", "request_id", "now"},
            {"project_root", "state_dir", "ticket_id", "external_thread_id", "runtime_attestation", "request_id", "now"},
        )
        root_guard(project, state, "monitor_receipt")
        ticket = ticket_path(state, arguments["ticket_id"], must_exist=True)
        with request_files(state, {"runtime": arguments["runtime_attestation"]}) as paths:
            return invoke(
                base
                + [
                    "record-launch-receipt",
                    "--ticket", str(ticket),
                    "--external-thread-id", opaque(arguments["external_thread_id"], "external-thread-id"),
                    "--runtime-attestation", str(paths["runtime"]),
                    "--request-id", opaque(arguments["request_id"], "request-id"),
                    "--now", opaque(arguments["now"], "now"),
                ]
            )
    if name == "pm_proxy_heartbeat":
        exact_keys(
            arguments,
            {"project_root", "state_dir", "ticket_id", "external_thread_id", "request_id", "lease_expires_at", "now"},
            {"project_root", "state_dir", "ticket_id", "external_thread_id", "request_id", "lease_expires_at", "now"},
        )
        root_guard(project, state, "monitor_receipt")
        ticket = ticket_path(state, arguments["ticket_id"], must_exist=True)
        return invoke(
            base
            + [
                "heartbeat",
                "--ticket", str(ticket),
                "--external-thread-id", opaque(arguments["external_thread_id"], "external-thread-id"),
                "--request-id", opaque(arguments["request_id"], "request-id"),
                "--lease-expires-at", opaque(arguments["lease_expires_at"], "lease-expires-at"),
                "--now", opaque(arguments["now"], "now"),
            ]
        )
    if name == "pm_proxy_lifecycle_watchdog":
        exact_keys(
            arguments,
            {"project_root", "state_dir", "ticket_id", "external_thread_id", "request", "successor_ticket_id"},
            {"project_root", "state_dir", "ticket_id", "external_thread_id", "request"},
        )
        root_guard(project, state, "monitor_handback")
        ticket = ticket_path(state, arguments["ticket_id"], must_exist=True)
        command = base + [
            "lifecycle-watchdog",
            "--ticket", str(ticket),
            "--external-thread-id", opaque(arguments["external_thread_id"], "external-thread-id"),
        ]
        successor = arguments.get("successor_ticket_id")
        if successor is not None:
            command += ["--successor-ticket", str(ticket_path(state, successor, must_exist=False))]
        with request_files(state, {"lifecycle": arguments["request"]}) as paths:
            return invoke(command + ["--request", str(paths["lifecycle"])])
    if name in {"pm_proxy_close_and_refill", "pm_proxy_watchdog_refill", "pm_proxy_slot_status"}:
        required = {"project_root", "state_dir", "refill_request"}
        allowed = set(required)
        if name == "pm_proxy_close_and_refill":
            required |= {"predecessor_ticket_id", "handback_request"}
            allowed |= {"predecessor_ticket_id", "handback_request"}
        exact_keys(arguments, allowed, required)
        if name == "pm_proxy_close_and_refill":
            predecessor = ticket_path(
                state, arguments["predecessor_ticket_id"], must_exist=True
            )
            try:
                ticket = strict_json(predecessor.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, McpError) as exc:
                raise McpError("ticket-invalid") from exc
            if not isinstance(ticket, dict) or not isinstance(ticket.get("receipt"), dict):
                raise McpError("launch-receipt-required")
            task_id = opaque(ticket.get("task_id"), "task-id")
            receipt = ticket["receipt"]
            evidence = [
                {
                    "kind": "launch_receipt",
                    "verified": True,
                    "task_id": task_id,
                    "receipt_id": f"receipt-{task_id}",
                    "external_thread_id": opaque(
                        receipt.get("external_thread_id"), "external-thread-id"
                    ),
                    "fencing_token": str(ticket.get("fencing_token")),
                    "lease_epoch": ticket.get("lease_epoch"),
                    "policy_snapshot_revision": str(
                        ticket.get("policy_snapshot_revision")
                    ),
                }
            ]
            root_guard(project, state, "refill_capacity", evidence=evidence)
        elif name == "pm_proxy_watchdog_refill":
            root_guard(project, state, "prepare_visible_task")
        else:
            root_guard(project, state, "monitor_receipt")
        values = {"refill": arguments["refill_request"]}
        if name == "pm_proxy_close_and_refill":
            values["handback"] = arguments["handback_request"]
        with request_files(state, values) as paths:
            refill_base = [
                sys.executable, str(REFILL),
                "--cli", str(firestarter_cli(project)),
                "--state-dir", str(state),
            ]
            if name == "pm_proxy_close_and_refill":
                return invoke(
                    refill_base
                    + [
                        "close-and-refill",
                        "--predecessor-ticket", str(predecessor),
                        "--handback-request", str(paths["handback"]),
                        "--refill-request", str(paths["refill"]),
                    ]
                )
            operation = "watchdog-refill" if name == "pm_proxy_watchdog_refill" else "slot-status"
            return invoke(refill_base + [operation, "--refill-request", str(paths["refill"])])
    if name == "pm_proxy_record_refill_receipt":
        exact_keys(
            arguments,
            {"project_root", "state_dir", "saga_id", "task_id", "external_thread_id", "runtime_attestation", "request_id", "now"},
            {"project_root", "state_dir", "saga_id", "task_id", "external_thread_id", "runtime_attestation", "request_id", "now"},
        )
        root_guard(project, state, "monitor_receipt")
        with request_files(state, {"runtime": arguments["runtime_attestation"]}) as paths:
            return invoke(
                [
                    sys.executable, str(REFILL),
                    "--cli", str(firestarter_cli(project)),
                    "--state-dir", str(state),
                    "record-refill-receipt",
                    "--saga-id", opaque(arguments["saga_id"], "saga-id"),
                    "--task-id", opaque(arguments["task_id"], "task-id"),
                    "--external-thread-id", opaque(arguments["external_thread_id"], "external-thread-id"),
                    "--runtime-attestation", str(paths["runtime"]),
                    "--request-id", opaque(arguments["request_id"], "request-id"),
                    "--now", opaque(arguments["now"], "now"),
                ]
            )
    if name == "pm_proxy_record_archive_receipt":
        exact_keys(
            arguments,
            {"project_root", "state_dir", "ticket_id", "request_id", "now"},
            {"project_root", "state_dir", "ticket_id", "request_id", "now"},
        )
        root_guard(project, state, "monitor_handback")
        return invoke(
            base
            + [
                "record-archive-receipt",
                "--ticket", str(ticket_path(state, arguments["ticket_id"], must_exist=True)),
                "--request-id", opaque(arguments["request_id"], "request-id"),
                "--now", opaque(arguments["now"], "now"),
            ]
        )
    raise McpError("unknown-tool")


COMMON_PROPERTIES = {
    "project_root": {"type": "string", "minLength": 1},
    "state_dir": {"type": "string", "minLength": 1},
}


def schema(extra: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {**COMMON_PROPERTIES, **extra},
        "required": ["project_root", "state_dir", *required],
        "additionalProperties": False,
    }


TOOLS: dict[str, dict[str, Any]] = {
    "pm_proxy_verify_runtime": {
        "description": "Verify the exact trusted Firestarter root and runtime policy without exposing shell access.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_root": COMMON_PROPERTIES["project_root"], "runtime_attestation": {"type": "object"}},
            "required": ["project_root", "runtime_attestation"],
            "additionalProperties": False,
        },
    },
    "pm_proxy_doctor": {"description": "Validate Firestarter CLI, schemas, private state, and quarantined rules.", "inputSchema": schema({}, [])},
    "pm_proxy_status": {"description": "Return receipt-derived orchestrator capacity and lifecycle truth.", "inputSchema": schema({}, [])},
    "pm_proxy_record_dispatcher_adoption": {
        "description": "Record a bounded live covered-path adoption proof while keeping universal enforcement explicitly false.",
        "inputSchema": schema({"request": {"type": "object"}}, ["request"]),
    },
    "pm_proxy_prepare_launch": {
        "description": "Atomically recycle the queue and reserve one visible worker before task creation.",
        "inputSchema": schema({"ticket_id": {"type": "string"}, "recycle_request": {"type": "object"}, "launch_request": {"type": "object"}}, ["ticket_id", "recycle_request", "launch_request"]),
    },
    "pm_proxy_record_launch_receipt": {
        "description": "Fence a newly created visible worker to its exact external task and runtime receipt.",
        "inputSchema": schema({"ticket_id": {"type": "string"}, "external_thread_id": {"type": "string"}, "runtime_attestation": {"type": "object"}, "request_id": {"type": "string"}, "now": {"type": "string"}}, ["ticket_id", "external_thread_id", "runtime_attestation", "request_id", "now"]),
    },
    "pm_proxy_heartbeat": {
        "description": "Renew a receipt-fenced worker lease before mutation or expiry.",
        "inputSchema": schema({"ticket_id": {"type": "string"}, "external_thread_id": {"type": "string"}, "request_id": {"type": "string"}, "lease_expires_at": {"type": "string"}, "now": {"type": "string"}}, ["ticket_id", "external_thread_id", "request_id", "lease_expires_at", "now"]),
    },
    "pm_proxy_lifecycle_watchdog": {
        "description": "Reconcile objective worker evidence after each message, wait, or status claim.",
        "inputSchema": schema({"ticket_id": {"type": "string"}, "external_thread_id": {"type": "string"}, "request": {"type": "object"}, "successor_ticket_id": {"type": "string"}}, ["ticket_id", "external_thread_id", "request"]),
    },
    "pm_proxy_close_and_refill": {
        "description": "Close a receipted predecessor and reserve refill in one durable saga.",
        "inputSchema": schema({"predecessor_ticket_id": {"type": "string"}, "handback_request": {"type": "object"}, "refill_request": {"type": "object"}}, ["predecessor_ticket_id", "handback_request", "refill_request"]),
    },
    "pm_proxy_watchdog_refill": {
        "description": "Recover a capacity deficit from complete current queue evidence.",
        "inputSchema": schema({"refill_request": {"type": "object"}}, ["refill_request"]),
    },
    "pm_proxy_slot_status": {
        "description": "Return active, reserved, runnable, and deficit truth for a complete candidate set.",
        "inputSchema": schema({"refill_request": {"type": "object"}}, ["refill_request"]),
    },
    "pm_proxy_record_refill_receipt": {
        "description": "Fence a reserved successor to the exact externally created task.",
        "inputSchema": schema({"saga_id": {"type": "string"}, "task_id": {"type": "string"}, "external_thread_id": {"type": "string"}, "runtime_attestation": {"type": "object"}, "request_id": {"type": "string"}, "now": {"type": "string"}}, ["saga_id", "task_id", "external_thread_id", "runtime_attestation", "request_id", "now"]),
    },
    "pm_proxy_record_archive_receipt": {
        "description": "Record external predecessor archival only after the refill fence permits it.",
        "inputSchema": schema({"ticket_id": {"type": "string"}, "request_id": {"type": "string"}, "now": {"type": "string"}}, ["ticket_id", "request_id", "now"]),
    },
}


def result(payload: Any, *, error: bool = False) -> dict[str, Any]:
    value = {
        "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True, separators=(",", ":"))}],
        "structuredContent": payload,
    }
    if error:
        value["isError"] = True
    return value


def handle(message: Mapping[str, Any]) -> dict[str, Any] | None:
    exact_keys(message, {"jsonrpc", "id", "method", "params"}, {"jsonrpc", "method"})
    if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        raise McpError("invalid-jsonrpc")
    request_id = message.get("id")
    if isinstance(request_id, bool) or not isinstance(request_id, (str, int, type(None))):
        raise McpError("invalid-request-id")
    method = message["method"]
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "pm-proxy-orchestrator", "version": SERVER_VERSION}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [{"name": name, **definition} for name, definition in sorted(TOOLS.items())]}}
    if method == "tools/call":
        params = message.get("params")
        if not isinstance(params, dict):
            raise McpError("invalid-tool-params")
        exact_keys(params, {"name", "arguments", "_meta"}, {"name", "arguments"})
        if "_meta" in params and not isinstance(params["_meta"], dict):
            raise McpError("invalid-tool-meta")
        name = params["name"]
        arguments = params["arguments"]
        if name not in TOOLS or not isinstance(arguments, dict):
            raise McpError("unknown-tool")
        try:
            payload = control_call(name, arguments)
            tool_result = result(payload)
        except McpError as exc:
            tool_result = result({"ok": False, "error": {"code": str(exc)}}, error=True)
        return {"jsonrpc": "2.0", "id": request_id, "result": tool_result}
    raise McpError("unknown-method")


def main() -> int:
    for raw in sys.stdin:
        response_id: Any = None
        try:
            if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
                raise McpError("request-too-large")
            message = strict_json(raw)
            if not isinstance(message, dict):
                raise McpError("invalid-jsonrpc")
            response_id = message.get("id")
            response = handle(message)
            if response is not None:
                print(json.dumps(response, sort_keys=True, separators=(",", ":")), flush=True)
        except McpError as exc:
            print(json.dumps({"jsonrpc": "2.0", "id": response_id, "error": {"code": -32602, "message": str(exc)}}, sort_keys=True, separators=(",", ":")), flush=True)
        except Exception:
            print(json.dumps({"jsonrpc": "2.0", "id": response_id, "error": {"code": -32603, "message": "internal-error"}}, sort_keys=True, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
