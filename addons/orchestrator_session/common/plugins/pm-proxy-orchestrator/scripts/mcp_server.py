#!/usr/bin/env python3
"""Local stdio MCP surface for typed Firestarter orchestration operations.

The server deliberately exposes no generic command, filesystem, or network
primitive.  Request objects are materialized only as owner-only temporary files
inside the selected private orchestrator state directory, passed to the pinned
bridge/refill programs without a shell, and removed before returning.
"""

from __future__ import annotations

import datetime as dt
import hashlib
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
SERVER_VERSION = "0.3.3"
MAX_MESSAGE_BYTES = 2_000_000
OPAQUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ADOPTION_VERSION = re.compile(
    rf"^{re.escape(SERVER_VERSION)}(?:\+codex\.\d{{14}})?$"
)
RUNTIME_PIN_NAME = "runtime-pin.json"
RUNTIME_PIN_VERSION = "1.0"


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


def project_candidate(value: Any) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise McpError("invalid-project-root")
    requested = Path(value)
    if requested.is_symlink():
        raise McpError("project-root-symlink")
    try:
        root = requested.resolve(strict=True)
    except OSError as exc:
        raise McpError("invalid-project-root") from exc
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
    matches = []
    for path in candidates:
        try:
            if (
                path.is_file()
                and not path.is_symlink()
                and path.resolve(strict=True) == path
            ):
                matches.append(path)
        except OSError:
            continue
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
    matches = []
    for path in candidates:
        try:
            if (
                path.is_file()
                and not path.is_symlink()
                and path.resolve(strict=True) == path
            ):
                matches.append(path)
        except OSError:
            continue
    if len(matches) != 1:
        raise McpError("runtime-verifier-missing")
    return matches[0]


def private_root() -> Path:
    configured_root = Path.home() / ".codex" / "orchestrator-state"
    try:
        if (
            configured_root.is_symlink()
            or (configured_root.stat().st_mode & 0o777) != 0o700
        ):
            raise McpError("state-root-not-private")
        return configured_root.resolve(strict=True)
    except OSError as exc:
        raise McpError("state-root-not-private") from exc


def runtime_bundle_files(project: Path) -> list[Path]:
    cli = firestarter_cli(project)
    control_root = cli.parent
    candidates = [
        cli,
        control_root / "VERSION",
        control_root / "root_role_guard.py",
        runtime_verifier(project),
        *sorted((control_root / "schemas").glob("*.json")),
    ]
    if len(candidates) < 5:
        raise McpError("runtime-bundle-incomplete")
    for path in candidates:
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise McpError("runtime-bundle-incomplete") from exc
        if not path.is_file() or path.is_symlink() or resolved != path:
            raise McpError("runtime-bundle-incomplete")
    return candidates


def runtime_bundle_digest(project: Path) -> str:
    digest = hashlib.sha256()
    for path in runtime_bundle_files(project):
        try:
            relative = path.relative_to(project).as_posix()
        except ValueError as exc:
            raise McpError("runtime-bundle-escape") from exc
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        try:
            contents = path.read_bytes()
        except OSError as exc:
            raise McpError("runtime-bundle-invalid") from exc
        digest.update(hashlib.sha256(contents).digest())
    return digest.hexdigest()


def runtime_pin() -> tuple[Path, dict[str, Any]] | None:
    path = private_root() / RUNTIME_PIN_NAME
    if not path.exists():
        return None
    try:
        if (
            not path.is_file()
            or path.is_symlink()
            or (path.stat().st_mode & 0o777) != 0o600
            or path.stat().st_size > 8192
        ):
            raise McpError("runtime-pin-not-private")
        value = strict_json(path.read_text(encoding="utf-8"))
    except McpError as exc:
        if str(exc) == "runtime-pin-not-private":
            raise
        raise McpError("runtime-pin-invalid") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise McpError("runtime-pin-invalid") from exc
    if not isinstance(value, dict):
        raise McpError("runtime-pin-invalid")
    try:
        exact_keys(
            value,
            {
                "pin_version",
                "plugin_version",
                "project_root",
                "control_version",
                "runtime_sha256",
                "configured_at",
            },
            {
                "pin_version",
                "plugin_version",
                "project_root",
                "control_version",
                "runtime_sha256",
                "configured_at",
            },
        )
    except McpError as exc:
        raise McpError("runtime-pin-invalid") from exc
    if (
        value["pin_version"] != RUNTIME_PIN_VERSION
        or value["plugin_version"] != SERVER_VERSION
        or not isinstance(value["control_version"], str)
        or OPAQUE.fullmatch(value["control_version"]) is None
        or not isinstance(value["runtime_sha256"], str)
        or SHA256.fullmatch(value["runtime_sha256"]) is None
        or not isinstance(value["configured_at"], str)
        or UTC.fullmatch(value["configured_at"]) is None
    ):
        raise McpError("runtime-pin-invalid")
    try:
        project = project_candidate(value["project_root"])
    except McpError as exc:
        raise McpError("runtime-pin-drift") from exc
    version_path = firestarter_cli(project).parent / "VERSION"
    try:
        control_version = version_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise McpError("runtime-pin-drift") from exc
    if (
        control_version != value["control_version"]
        or runtime_bundle_digest(project) != value["runtime_sha256"]
    ):
        raise McpError("runtime-pin-drift")
    return project, value


def absolute_project(value: Any) -> Path:
    pin = runtime_pin()
    if pin is None:
        return project_candidate(value)
    project, _value = pin
    if value is not None:
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise McpError("invalid-project-root")
        if Path(value).is_symlink():
            raise McpError("project-root-symlink")
        try:
            requested = Path(value).resolve(strict=True)
        except OSError as exc:
            raise McpError("invalid-project-root") from exc
        if requested != project:
            raise McpError("runtime-project-root-mismatch")
    return project


def runtime_pin_summary() -> dict[str, Any]:
    pin = runtime_pin()
    if pin is None:
        return {
            "configured": False,
            "verified": False,
            "plugin_version": SERVER_VERSION,
        }
    project, value = pin
    return {
        "configured": True,
        "verified": True,
        "plugin_version": SERVER_VERSION,
        "project_root": str(project),
        "control_version": value["control_version"],
        "runtime_sha256": value["runtime_sha256"],
        "configured_at": value["configured_at"],
    }


def private_state(value: Any) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise McpError("invalid-state-dir")
    requested = Path(value)
    if requested.is_symlink():
        raise McpError("state-dir-symlink")
    try:
        path = requested.resolve(strict=True)
    except OSError as exc:
        raise McpError("invalid-state-dir") from exc
    allowed_root = private_root()
    try:
        path.relative_to(allowed_root)
    except ValueError as exc:
        raise McpError("state-dir-outside-private-root") from exc
    try:
        if path.is_symlink() or (path.stat().st_mode & 0o777) != 0o700:
            raise McpError("state-dir-not-private")
    except OSError as exc:
        raise McpError("invalid-state-dir") from exc
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


def payload_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = payload.get("result")
    if not isinstance(value, dict):
        raise McpError("control-response-invalid")
    return value


def operational_safety(status: Mapping[str, Any]) -> dict[str, Any]:
    pin = runtime_pin_summary()
    lifecycle = status.get("lifecycle_watchdog")
    if not isinstance(lifecycle, dict):
        raise McpError("control-response-invalid")
    adoption = lifecycle.get("dispatcher_adoption")
    adoption_version_matches = bool(
        isinstance(adoption, dict)
        and isinstance(adoption.get("plugin_version"), str)
        and ADOPTION_VERSION.fullmatch(adoption["plugin_version"]) is not None
    )
    covered = bool(
        lifecycle.get("covered_path_dispatcher_enforcement")
        and adoption_version_matches
    )
    ready = bool(pin["verified"] and covered)
    return {
        "runtime_pin_verified": pin["verified"],
        "dispatcher_adoption_version_matches": adoption_version_matches,
        "covered_path_dispatcher_enforcement": covered,
        "platform_dispatcher_enforcement": False,
        "automatic_launch_refill_allowed": ready,
        "covered_path_automatic_launch_refill_allowed": ready,
        "unattended_automatic_launch_refill_allowed": False,
        "automatic_launch_refill_scope": (
            "COVERED_PATH_ONLY" if ready else "DISABLED"
        ),
        "universal_dispatcher_enforcement": False,
    }


def require_runtime_pin(project: Path) -> None:
    pin = runtime_pin()
    if pin is None:
        raise McpError("runtime-pin-required")
    if pin[0] != project:
        raise McpError("runtime-project-root-mismatch")


def require_automatic_control_ready(project: Path, state: Path) -> None:
    require_runtime_pin(project)
    status_payload = invoke(bridge_base(project, state) + ["status"])
    safety = operational_safety(payload_result(status_payload))
    if safety["automatic_launch_refill_allowed"] is not True:
        raise McpError("dispatcher-adoption-required")


def control_call(name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    if name == "pm_proxy_verify_runtime":
        exact_keys(
            arguments,
            {"project_root", "runtime_attestation"},
            {"runtime_attestation"},
        )
        project = absolute_project(arguments.get("project_root"))
        state_root = private_root()
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
        exact_keys(arguments, {"project_root", "state_dir"}, {"state_dir"})
        payload = invoke(base + ["doctor"])
        payload_result(payload)["runtime_pin"] = runtime_pin_summary()
        return payload
    if name == "pm_proxy_status":
        exact_keys(arguments, {"project_root", "state_dir", "now"}, {"state_dir"})
        root_guard(project, state, "monitor_receipt")
        command = base + ["status"]
        if "now" in arguments:
            command += ["--now", opaque(arguments["now"], "now")]
        payload = invoke(command)
        status = payload_result(payload)
        status["runtime_pin"] = runtime_pin_summary()
        status["operational_safety"] = operational_safety(status)
        return payload
    if name == "pm_proxy_reconcile_expired_lease":
        exact_keys(
            arguments,
            {"project_root", "state_dir", "ticket_id", "request_id", "now"},
            {"state_dir", "ticket_id", "request_id", "now"},
        )
        root_guard(project, state, "deduplicate_ownership")
        return invoke(
            base
            + [
                "reconcile-expired-lease",
                "--ticket",
                str(ticket_path(state, arguments["ticket_id"], must_exist=True)),
                "--request-id",
                opaque(arguments["request_id"], "request-id"),
                "--now",
                opaque(arguments["now"], "now"),
            ]
        )
    if name == "pm_proxy_prepare_launch":
        exact_keys(
            arguments,
            {"project_root", "state_dir", "ticket_id", "recycle_request", "launch_request"},
            {"state_dir", "ticket_id", "recycle_request", "launch_request"},
        )
        require_automatic_control_ready(project, state)
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
            {"state_dir", "ticket_id", "external_thread_id", "runtime_attestation", "request_id", "now"},
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
            {"state_dir", "ticket_id", "external_thread_id", "request_id", "lease_expires_at", "now"},
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
            {"state_dir", "ticket_id", "external_thread_id", "request"},
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
        required = {"state_dir", "refill_request"}
        allowed = {"project_root", *required}
        if name == "pm_proxy_close_and_refill":
            required |= {"predecessor_ticket_id", "handback_request"}
            allowed |= {"predecessor_ticket_id", "handback_request"}
        exact_keys(arguments, allowed, required)
        if name == "pm_proxy_close_and_refill":
            require_automatic_control_ready(project, state)
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
            require_automatic_control_ready(project, state)
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
            {"state_dir", "saga_id", "task_id", "external_thread_id", "runtime_attestation", "request_id", "now"},
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
            {"state_dir", "ticket_id", "request_id", "now"},
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
        "required": ["state_dir", *required],
        "additionalProperties": False,
    }


TOOLS: dict[str, dict[str, Any]] = {
    "pm_proxy_verify_runtime": {
        "description": "Verify the exact trusted Firestarter root and runtime policy without exposing shell access.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_root": COMMON_PROPERTIES["project_root"], "runtime_attestation": {"type": "object"}},
            "required": ["runtime_attestation"],
            "additionalProperties": False,
        },
    },
    "pm_proxy_doctor": {"description": "Validate the pinned or explicitly selected Firestarter CLI, schemas, private state, and quarantined rules.", "inputSchema": schema({}, [])},
    "pm_proxy_status": {"description": "Return receipt-derived orchestrator capacity, lifecycle truth, and automatic-control readiness at an optional explicit clock.", "inputSchema": schema({"now": {"type": "string"}}, [])},
    "pm_proxy_reconcile_expired_lease": {
        "description": "Retire one exact expired receipt-fenced owner and release its capacity without takeover, closure, archive, or refill.",
        "inputSchema": schema({"ticket_id": {"type": "string"}, "request_id": {"type": "string"}, "now": {"type": "string"}}, ["ticket_id", "request_id", "now"]),
    },
    "pm_proxy_prepare_launch": {
        "description": "Atomically recycle the queue and reserve one visible worker only after runtime-pin and covered-dispatcher adoption proofs.",
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
        "description": "Close a receipted predecessor and reserve refill only after runtime-pin and covered-dispatcher adoption proofs.",
        "inputSchema": schema({"predecessor_ticket_id": {"type": "string"}, "handback_request": {"type": "object"}, "refill_request": {"type": "object"}}, ["predecessor_ticket_id", "handback_request", "refill_request"]),
    },
    "pm_proxy_watchdog_refill": {
        "description": "Recover a capacity deficit from complete current queue evidence only after runtime-pin and covered-dispatcher adoption proofs.",
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
