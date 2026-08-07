#!/usr/bin/env python3
"""Fail-closed bridge for Firestarter orchestrator-control interface 1.0."""

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
import tempfile
from pathlib import Path
from typing import Any


BRIDGE_VERSION = "1.4"
INTERFACE_VERSION = "1.0"
TICKET_VERSION = "1.3"
LEGACY_TICKET_VERSIONS = {"1.0", "1.2"}
SUPPORTED_SCHEMA_VERSIONS = {"1.0", "1.1", "1.2", "1.3", "1.4"}
LAUNCH_RECEIPT_TTL_SECONDS = 300
MAX_MACHINE_OUTPUT = 1_048_576
MAX_REQUEST_BYTES = 524_288
MAX_LEGACY_TICKETS = 4_096
CLI_TIMEOUT_SECONDS = 15
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
RUNTIME_POLICY_REQUIRED = {
    "root_model": "gpt-5.6-sol",
    "root_reasoning_effort": "xhigh",
    "root_service_tier": "priority",
    "root_fast_mode": True,
    "worker_model": "gpt-5.6-sol",
    "worker_reasoning_effort": "xhigh",
    "worker_service_tier": "priority",
    "worker_fast_mode": True,
    "service_tier_attestation_allowed": ["config-verified", "runtime"],
    "parent_attestation_required": True,
}
OWNER_DECISION_SINK_THREAD_ID = "019fcb3b-f5dc-7df3-9fe1-efe5b2e09a69"
ARCHIVE_LOCAL_OUTCOMES = {
    "REFILL_SATISFIED",
    "EMPTY",
    "OWNER_GATED",
    "CAPACITY_FULL",
}
ARCHIVE_CONTROL_OUTCOMES = {
    "SUCCESSOR_RECEIPTED",
    "EMPTY",
    "OWNER_GATED",
    "CAPACITY_FULL",
}
EXPIRED_ARCHIVE_DISPOSITIONS = {
    "completed",
    "completed_local_only",
    "completed_local_artifact",
}

REQUIRED_SCHEMAS = {
    "shared.schema.json": "shared-1.0.schema.json",
    "machine-response.schema.json": "machine-response-1.0.schema.json",
    "prepare-launch.request.schema.json": "prepare-launch-request-1.0.schema.json",
    "prepare-launch.response.schema.json": "prepare-launch-response-1.0.schema.json",
    "receipt.request.schema.json": "receipt-request-1.0.schema.json",
    "heartbeat.request.schema.json": "heartbeat-request-1.0.schema.json",
    "classify-decision.request.schema.json": "classify-decision-request-1.0.schema.json",
    "classify-decision.response.schema.json": "classify-decision-response-1.0.schema.json",
    "record-handback.request.schema.json": "record-handback-request-1.0.schema.json",
    "record-handback.response.schema.json": "record-handback-response-1.0.schema.json",
    "record-policy-rule.request.schema.json": "record-policy-rule-request-1.0.schema.json",
    "recycle-queue.request.schema.json": "recycle-queue-request-1.0.schema.json",
    "recycle-queue.response.schema.json": "recycle-queue-response-1.0.schema.json",
}
CAPACITY_SCHEMAS = {
    "capacity-watchdog.request.schema.json": "capacity-watchdog-request-1.0.schema.json",
    "capacity-watchdog.response.schema.json": "capacity-watchdog-response-1.0.schema.json",
    "configure-capacity.request.schema.json": "configure-capacity-request-1.0.schema.json",
    "configure-capacity.response.schema.json": "configure-capacity-response-1.0.schema.json",
    "reconcile-external-task.request.schema.json": "reconcile-external-task-request-1.0.schema.json",
    "reconcile-external-task.response.schema.json": "reconcile-external-task-response-1.0.schema.json",
}
DURATION_SCHEMAS = {
    "duration-estimate.request.schema.json": "duration-estimate-request-1.0.schema.json",
    "duration-estimate.response.schema.json": "duration-estimate-response-1.0.schema.json",
    "duration-schedule.request.schema.json": "duration-schedule-request-1.0.schema.json",
    "duration-schedule.response.schema.json": "duration-schedule-response-1.0.schema.json",
    "record-duration-progress.request.schema.json": "record-duration-progress-request-1.0.schema.json",
    "record-duration-progress.response.schema.json": "record-duration-progress-response-1.0.schema.json",
    "record-duration-observation.request.schema.json": "record-duration-observation-request-1.0.schema.json",
    "record-duration-observation.response.schema.json": "record-duration-observation-response-1.0.schema.json",
    "record-setup-failure.request.schema.json": "record-setup-failure-request-1.0.schema.json",
    "record-setup-failure.response.schema.json": "record-setup-failure-response-1.0.schema.json",
}
ROOT_GUARD_SCHEMAS = {
    "root-role-guard.request.schema.json": "root-role-guard-request-1.0.schema.json",
    "root-role-guard.response.schema.json": "root-role-guard-response-1.0.schema.json",
}
LIFECYCLE_SCHEMAS = {
    "lifecycle-watchdog.request.schema.json": "lifecycle-watchdog-request-1.0.schema.json",
    "lifecycle-watchdog.response.schema.json": "lifecycle-watchdog-response-1.0.schema.json",
    "dispatcher-adoption.request.schema.json": "dispatcher-adoption-request-1.0.schema.json",
    "dispatcher-adoption.response.schema.json": "dispatcher-adoption-response-1.0.schema.json",
    "reconcile-expired-lease.request.schema.json": "reconcile-expired-lease-request-1.0.schema.json",
    "acknowledge-control-schema-hold.request.schema.json": "acknowledge-control-schema-hold-request-1.0.schema.json",
    "acknowledge-control-schema-hold.response.schema.json": "acknowledge-control-schema-hold-response-1.0.schema.json",
}
LEGACY_ARCHIVE_SCHEMAS = {
    "reconcile-legacy-archive.request.schema.json": "reconcile-legacy-archive-request-1.0.schema.json",
    "reconcile-legacy-archive.response.schema.json": "reconcile-legacy-archive-response-1.0.schema.json",
    "reconcile-stale-present-archive.request.schema.json": "reconcile-stale-present-archive-request-1.0.schema.json",
    "reconcile-stale-present-archive.response.schema.json": "reconcile-stale-present-archive-response-1.0.schema.json",
}
FEDERATION_SCHEMAS = {
    "authority-transfer-receipt.schema.json": "authority-transfer-receipt-1.0.schema.json",
    "prepare-authority-transfer.request.schema.json": "prepare-authority-transfer-request-1.0.schema.json",
    "prepare-authority-transfer.response.schema.json": "prepare-authority-transfer-response-1.0.schema.json",
    "stage-federation.request.schema.json": "stage-federation-request-1.0.schema.json",
    "stage-federation.response.schema.json": "stage-federation-response-1.0.schema.json",
    "finalize-authority-transfer.request.schema.json": "finalize-authority-transfer-request-1.0.schema.json",
    "finalize-authority-transfer.response.schema.json": "finalize-authority-transfer-response-1.0.schema.json",
    "activate-federation.request.schema.json": "activate-federation-request-1.0.schema.json",
    "activate-federation.response.schema.json": "activate-federation-response-1.0.schema.json",
    "enable-subordinate.request.schema.json": "enable-subordinate-request-1.0.schema.json",
    "enable-subordinate.response.schema.json": "enable-subordinate-response-1.0.schema.json",
    "abort-authority-transfer.request.schema.json": "abort-authority-transfer-request-1.0.schema.json",
    "abort-authority-transfer.response.schema.json": "abort-authority-transfer-response-1.0.schema.json",
}

SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential_value",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "session_token",
    "token",
}
FORBIDDEN_DURABLE_KEYS = {
    "command",
    "command_output",
    "diff",
    "prompt",
    "prompt_hash",
    "raw_prompt",
    "shell",
    "transcript",
}
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:ghp|github_pat|glpat)-?[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{20,}\b", re.IGNORECASE),
    re.compile(r"(?i)\b(?:password|secret|token|api[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"https?://[^\s?#]+[?&](?:token|key|secret|code)=", re.IGNORECASE),
]
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
SEMVER_PATTERN = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


class BridgeError(Exception):
    def __init__(self, code: str, message: str, *, exit_status: int = 4, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_status = exit_status
        self.details = details or {}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def parse_time(value: str) -> dt.datetime:
    if not isinstance(value, str):
        raise BridgeError("TIME_INVALID", "timestamp must be a string")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BridgeError("TIME_INVALID", "timestamp must be ISO-8601 with timezone") from exc
    if parsed.tzinfo is None:
        raise BridgeError("TIME_INVALID", "timestamp must include timezone")
    return parsed.astimezone(dt.timezone.utc)


def format_time(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def emit(value: dict[str, Any], *, stream: Any = sys.stdout) -> None:
    stream.write(canonical(value) + "\n")
    stream.flush()


def fail_payload(error: BridgeError) -> dict[str, Any]:
    return {
        "interface_version": INTERFACE_VERSION,
        "ok": False,
        "error": {
            "code": error.code,
            "message": error.message,
            "details": error.details,
        },
    }


def success(operation: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "bridge_version": BRIDGE_VERSION,
        "interface_version": INTERFACE_VERSION,
        "ok": True,
        "operation": operation,
        "result": result,
    }


def require_absolute(path_value: str, label: str, *, must_exist: bool = True) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        raise BridgeError("PATH_INVALID", f"{label} must be absolute")
    normalized = Path(os.path.abspath(path))
    if must_exist and not normalized.exists():
        raise BridgeError("PATH_MISSING", f"{label} is missing")
    if must_exist:
        try:
            if normalized.resolve(strict=True) != normalized:
                raise BridgeError("PATH_UNSAFE", f"{label} cannot contain symlinks")
        except OSError as exc:
            raise BridgeError("PATH_UNSAFE", f"{label} cannot be resolved") from exc
    return normalized


def validate_private_dir(path_value: str, label: str) -> Path:
    path = require_absolute(path_value, label)
    if not path.is_dir():
        raise BridgeError("PATH_INVALID", f"{label} must be a directory")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o700:
        raise BridgeError("PATH_PERMISSIONS", f"{label} must have mode 0700")
    if hasattr(os, "getuid") and path.stat().st_uid != os.getuid():
        raise BridgeError("PATH_OWNERSHIP", f"{label} must be owned by the current user")
    return path


def load_json_file(path_value: str, label: str) -> dict[str, Any]:
    if path_value == "-":
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    else:
        path = require_absolute(path_value, label)
        if not path.is_file():
            raise BridgeError("PATH_INVALID", f"{label} must be a file")
        if path.stat().st_size > MAX_REQUEST_BYTES:
            raise BridgeError("REQUEST_TOO_LARGE", f"{label} exceeds size limit", exit_status=2)
        raw = path.read_bytes()
    if len(raw) > MAX_REQUEST_BYTES:
        raise BridgeError("REQUEST_TOO_LARGE", f"{label} exceeds size limit", exit_status=2)
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeError("JSON_INVALID", f"{label} must be one UTF-8 JSON object", exit_status=2) from exc
    if not isinstance(parsed, dict):
        raise BridgeError("SCHEMA_INVALID", f"{label} must be an object", exit_status=2)
    return parsed


def scan_strings(value: Any, *, durable: bool, key_path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise BridgeError("PRIVACY_DENIED", "object keys must be strings", exit_status=2)
            lowered = key.lower()
            if lowered in SECRET_KEYS:
                raise BridgeError("PRIVACY_DENIED", f"secret-bearing field is forbidden: {key}", exit_status=2)
            if durable and lowered in FORBIDDEN_DURABLE_KEYS:
                raise BridgeError("PRIVACY_DENIED", f"durable request field is forbidden: {key}", exit_status=2)
            scan_strings(child, durable=durable, key_path=key_path + (key,))
        return
    if isinstance(value, list):
        for child in value:
            scan_strings(child, durable=durable, key_path=key_path)
        return
    if not isinstance(value, str):
        return
    if len(value) > 65_536:
        raise BridgeError("PRIVACY_DENIED", "string exceeds privacy-safe bound", exit_status=2)
    if "\x00" in value or "\r" in value:
        raise BridgeError("PRIVACY_DENIED", "control characters are forbidden", exit_status=2)
    for pattern in SECRET_PATTERNS:
        if pattern.search(value):
            raise BridgeError("PRIVACY_DENIED", "secret-like content rejected", exit_status=2)
    if durable and EMAIL_PATTERN.search(value):
        raise BridgeError("PRIVACY_DENIED", "use a non-email alias in durable state", exit_status=2)


def validate_request(request: dict[str, Any], *, durable: bool) -> None:
    if request.get("interface_version") != INTERFACE_VERSION:
        raise BridgeError(
            "INTERFACE_INCOMPATIBLE",
            f"request interface_version must be {INTERFACE_VERSION}",
            exit_status=2,
        )
    scan_strings(request, durable=durable)


def validate_policy_request(request: dict[str, Any]) -> None:
    if request.get("interface_version") != INTERFACE_VERSION:
        raise BridgeError(
            "INTERFACE_INCOMPATIBLE",
            f"request interface_version must be {INTERFACE_VERSION}",
            exit_status=2,
        )
    rule = request.get("rule")
    if not isinstance(rule, dict):
        raise BridgeError("SCHEMA_INVALID", "record-policy-rule requires a rule object", exit_status=2)
    directive = rule.get("directive")
    if not isinstance(directive, dict) or directive.get("args") != {}:
        raise BridgeError(
            "ARBITRARY_EXECUTION_DENIED",
            "rule.directive.args must be empty; executable policy is forbidden",
            exit_status=2,
        )
    scan_strings(request, durable=True)
    provenance = rule.get("provenance")
    if not isinstance(provenance, dict):
        raise BridgeError("SCHEMA_INVALID", "rule provenance is required", exit_status=2)
    summary = provenance.get("redacted_summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 512:
        raise BridgeError("PRIVACY_DENIED", "bounded redacted_summary is required", exit_status=2)


def validate_handback_request(request: dict[str, Any]) -> None:
    if request.get("interface_version") != INTERFACE_VERSION:
        raise BridgeError(
            "INTERFACE_INCOMPATIBLE",
            f"request interface_version must be {INTERFACE_VERSION}",
            exit_status=2,
        )
    sanitized = json.loads(canonical(request))
    successor = sanitized.get("successor_request")
    if isinstance(successor, dict) and "prompt" in successor:
        prompt = successor.pop("prompt")
        scan_strings(prompt, durable=False)
    scan_strings(sanitized, durable=True)


def validate_setup_failure_request(request: dict[str, Any]) -> None:
    if request.get("interface_version") != INTERFACE_VERSION:
        raise BridgeError("INTERFACE_INCOMPATIBLE", "setup-failure interface is incompatible", exit_status=2)
    sanitized = json.loads(canonical(request))
    candidates = sanitized.get("successor_candidates")
    if not isinstance(candidates, list):
        raise BridgeError("SCHEMA_INVALID", "successor_candidates must be an array", exit_status=2)
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.pop("prompt", None), str):
            raise BridgeError("SCHEMA_INVALID", "each setup-failure successor requires an ephemeral prompt", exit_status=2)
    scan_strings(sanitized, durable=True)


def validate_owner_decision_route_request(request: dict[str, Any]) -> None:
    required = {
        "interface_version", "route_request_id", "source_thread_id",
        "sink_thread_id", "origin", "recursion_depth", "decision_request",
        "approval", "now",
    }
    if not isinstance(request, dict) or set(request) != required:
        raise BridgeError(
            "SCHEMA_INVALID", "owner-decision route fields are invalid", exit_status=2
        )
    if request.get("interface_version") != INTERFACE_VERSION:
        raise BridgeError("INTERFACE_INCOMPATIBLE", "route interface is incompatible", exit_status=2)
    if (
        request.get("sink_thread_id") != OWNER_DECISION_SINK_THREAD_ID
        or request.get("source_thread_id") == OWNER_DECISION_SINK_THREAD_ID
        or request.get("origin") != "WORKER"
        or request.get("recursion_depth") != 0
    ):
        raise BridgeError(
            "DECISION_ROUTE_RECURSION_DENIED",
            "owner-decision sink cannot originate, recurse, or gain authority",
            exit_status=2,
        )
    decision = request.get("decision_request")
    approval = request.get("approval")
    if not isinstance(decision, dict) or not isinstance(approval, dict):
        raise BridgeError("SCHEMA_INVALID", "typed decision and approval are required", exit_status=2)
    if decision.get("interface_version") != INTERFACE_VERSION or decision.get("now") != request.get("now"):
        raise BridgeError("SCHEMA_INVALID", "decision route clock or interface changed", exit_status=2)
    if set(approval) != {"request_id", "decision_code", "option_codes", "evidence_refs"}:
        raise BridgeError("SCHEMA_INVALID", "approval envelope fields are invalid", exit_status=2)
    if approval.get("request_id") != decision.get("request_id"):
        raise BridgeError("DECISION_ROUTE_CONFLICT", "approval request does not match classification", exit_status=3)
    for key in ("route_request_id", "source_thread_id"):
        value = request.get(key)
        if not isinstance(value, str) or ID_RE.fullmatch(value) is None:
            raise BridgeError("SCHEMA_INVALID", f"{key} is invalid", exit_status=2)
    for key in ("request_id", "decision_code"):
        value = approval.get(key)
        if not isinstance(value, str) or ID_RE.fullmatch(value) is None:
            raise BridgeError("SCHEMA_INVALID", f"approval.{key} is invalid", exit_status=2)
    for key, maximum in (("option_codes", 8), ("evidence_refs", 16)):
        values = approval.get(key)
        if (
            not isinstance(values, list)
            or not values
            or len(values) > maximum
            or len(values) != len(set(values))
            or any(not isinstance(item, str) or ID_RE.fullmatch(item) is None for item in values)
        ):
            raise BridgeError("SCHEMA_INVALID", f"approval.{key} is invalid", exit_status=2)
    forbidden = {
        "prompt", "command", "command_text", "hash", "secret", "secrets",
        "credential", "credentials", "credential_url", "private_text",
        "patient_text", "url",
    }
    stack = [request]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if any(str(key).lower() in forbidden for key in current):
                raise BridgeError("PRIVACY_DENIED", "decision route contains a forbidden field", exit_status=2)
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    scan_strings(request, durable=True)


def version_tuple(value: str, label: str) -> tuple[int, int]:
    parts = value.split(".")
    if len(parts) < 2 or not all(part.isdigit() for part in parts[:2]):
        raise BridgeError("SCHEMA_INCOMPATIBLE", f"{label} is invalid")
    return int(parts[0]), int(parts[1])


def schema_at_least(value: str, minimum: tuple[int, int]) -> bool:
    return version_tuple(value, "schema_version") >= minimum


def validate_schema_files(root: Path, required: dict[str, str]) -> None:
    schemas = root / "schemas"
    for filename, id_suffix in required.items():
        schema_path = schemas / filename
        if not schema_path.is_file():
            raise BridgeError("SCHEMA_INCOMPATIBLE", f"required schema missing: {filename}")
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BridgeError("SCHEMA_INCOMPATIBLE", f"schema is invalid JSON: {filename}") from exc
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or not schema_id.endswith(id_suffix):
            raise BridgeError(
                "SCHEMA_INCOMPATIBLE",
                f"schema interface mismatch: {filename}",
                details={"id": schema_id},
            )


def validate_installation(cli_value: str) -> tuple[Path, str]:
    cli = require_absolute(cli_value, "Firestarter CLI")
    if not cli.is_file() or cli.name != "orchestrator_control.py":
        raise BridgeError("CLI_INVALID", "Firestarter CLI must be orchestrator_control.py")
    root = cli.parent
    version_path = root / "VERSION"
    schemas = root / "schemas"
    if not version_path.is_file() or not schemas.is_dir():
        raise BridgeError("CLI_INCOMPATIBLE", "Firestarter VERSION or schemas directory is missing")
    version = version_path.read_text(encoding="utf-8").strip()
    match = SEMVER_PATTERN.fullmatch(version)
    if not match or int(match.group("major")) != 1:
        raise BridgeError(
            "CLI_INCOMPATIBLE",
            "Firestarter CLI must use compatible semantic version 1.x",
            details={"found": version},
        )
    required_schemas = dict(REQUIRED_SCHEMAS)
    if int(match.group("minor")) >= 1:
        required_schemas.update(CAPACITY_SCHEMAS)
    if int(match.group("minor")) >= 2:
        required_schemas.update(DURATION_SCHEMAS)
        required_schemas.update(ROOT_GUARD_SCHEMAS)
        if not (root / "root_role_guard.py").is_file():
            raise BridgeError("CLI_INCOMPATIBLE", "schema 1.2 root-role guard is missing")
    if int(match.group("minor")) >= 3:
        required_schemas.update(LIFECYCLE_SCHEMAS)
    if int(match.group("minor")) >= 4:
        required_schemas.update(FEDERATION_SCHEMAS)
        required_schemas.update(LEGACY_ARCHIVE_SCHEMAS)
    validate_schema_files(root, required_schemas)
    return cli, version


def validate_machine_success(payload: Any, expected_operation: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise BridgeError("MACHINE_RESPONSE_INVALID", "CLI success must be an object")
    if set(payload) != {"interface_version", "ok", "operation", "result"}:
        raise BridgeError("MACHINE_RESPONSE_INVALID", "CLI success fields are incompatible")
    if payload["interface_version"] != INTERFACE_VERSION or payload["ok"] is not True:
        raise BridgeError("INTERFACE_INCOMPATIBLE", "CLI response interface is incompatible")
    if payload["operation"] != expected_operation or not isinstance(payload["result"], dict):
        raise BridgeError("MACHINE_RESPONSE_INVALID", "CLI operation/result is incompatible")
    return payload["result"]


def validate_machine_error(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise BridgeError("MACHINE_RESPONSE_INVALID", "CLI failure must be an object")
    if set(payload) != {"interface_version", "ok", "error"}:
        raise BridgeError("MACHINE_RESPONSE_INVALID", "CLI failure fields are incompatible")
    if payload["interface_version"] != INTERFACE_VERSION or payload["ok"] is not False:
        raise BridgeError("INTERFACE_INCOMPATIBLE", "CLI failure interface is incompatible")
    error = payload.get("error")
    if not isinstance(error, dict) or set(error) != {"code", "message", "details"}:
        raise BridgeError("MACHINE_RESPONSE_INVALID", "CLI error body is incompatible")


def run_cli(
    cli: Path,
    state_dir: Path,
    command: str,
    *,
    request: dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    allowed = {
        "init",
        "status",
        "record-policy-rule",
        "effective-rules",
        "prepare-launch",
        "record-launch-receipt",
        "reconcile-external-task",
        "classify-decision",
        "record-heartbeat",
        "takeover-lease",
        "reconcile-expired-lease",
        "record-handback",
        "record-archive-receipt",
        "reconcile-legacy-archive",
        "reconcile-stale-present-archive",
        "capacity-watchdog",
        "configure-capacity",
        "lifecycle-watchdog",
        "acknowledge-control-schema-hold",
        "recycle-queue",
        "record-duration-progress",
        "record-duration-observation",
        "duration-estimate",
        "duration-schedule",
        "record-dispatcher-adoption",
        "record-setup-failure",
    }
    if command not in allowed:
        raise BridgeError("COMMAND_DENIED", "command is not allowlisted", exit_status=2)
    argv = [sys.executable, str(cli), "--state-dir", str(state_dir), command]
    stdin_text = None
    if command in {"init", "status"} and now is not None:
        argv.extend(["--now", now])
    if command == "init":
        if now is None:
            raise BridgeError("SCHEMA_INVALID", "init requires --now", exit_status=2)
    elif request is not None:
        argv.extend(["--request", "-"])
        stdin_text = canonical(request)
    try:
        completed = subprocess.run(
            argv,
            input=stdin_text,
            text=True,
            capture_output=True,
            timeout=CLI_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BridgeError("STATE_UNAVAILABLE", "Firestarter CLI timed out; state may be locked") from exc
    if len(completed.stdout.encode("utf-8")) > MAX_MACHINE_OUTPUT or len(completed.stderr.encode("utf-8")) > MAX_MACHINE_OUTPUT:
        raise BridgeError("MACHINE_RESPONSE_INVALID", "CLI output exceeded bounded size")
    if completed.returncode == 0:
        if completed.stderr.strip():
            raise BridgeError("MACHINE_RESPONSE_INVALID", "CLI emitted stderr on success")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise BridgeError("MACHINE_RESPONSE_INVALID", "CLI success was not one JSON object") from exc
        return validate_machine_success(payload, command)
    if completed.returncode not in {2, 3, 4}:
        raise BridgeError(
            "STATE_UNAVAILABLE",
            "Firestarter CLI used an unsupported exit status",
            details={"exit_status": completed.returncode},
        )
    if completed.stdout.strip():
        raise BridgeError("MACHINE_RESPONSE_INVALID", "CLI emitted success output on failure")
    try:
        payload = json.loads(completed.stderr)
    except json.JSONDecodeError as exc:
        raise BridgeError("MACHINE_RESPONSE_INVALID", "CLI failure was not one JSON object") from exc
    validate_machine_error(payload)
    error = payload["error"]
    raise BridgeError(
        error["code"],
        error["message"],
        exit_status=completed.returncode,
        details=error["details"],
    )


def run_root_guard(
    cli: Path,
    state_dir: Path,
    request: dict[str, Any],
) -> dict[str, Any]:
    guard = cli.parent / "root_role_guard.py"
    if not guard.is_file() or guard.is_symlink():
        raise BridgeError(
            "ROOT_GUARD_UNAVAILABLE",
            "root dispatcher guard is unavailable; task execution remains denied",
        )
    argv = [
        sys.executable,
        str(guard),
        "--state-file",
        str(state_dir / "root-role-audit.json"),
        "--request",
        "-",
        "evaluate",
    ]
    try:
        completed = subprocess.run(
            argv,
            input=canonical(request),
            text=True,
            capture_output=True,
            timeout=CLI_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BridgeError("ROOT_GUARD_UNAVAILABLE", "root-role guard timed out") from exc
    raw = completed.stdout if completed.returncode == 0 else completed.stderr
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BridgeError("MACHINE_RESPONSE_INVALID", "root-role guard returned invalid JSON") from exc
    if completed.returncode != 0:
        error = payload.get("error", {})
        raise BridgeError(
            error.get("code", "ROOT_GUARD_DENIED"),
            error.get("message", "root-role guard failed closed"),
            exit_status=2,
        )
    result = validate_machine_success(payload, "root-role-guard")
    if result.get("decision") not in {"ALLOW", "DENY"}:
        raise BridgeError("MACHINE_RESPONSE_INVALID", "root-role guard decision is invalid")
    return result


def doctor(cli: Path, state_dir: Path, version: str) -> dict[str, Any]:
    status = run_cli(cli, state_dir, "status")
    if status.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        raise BridgeError("SCHEMA_INCOMPATIBLE", "ledger schema_version is incompatible")
    schema_version = status["schema_version"]
    required = dict(REQUIRED_SCHEMAS)
    if schema_at_least(schema_version, (1, 1)):
        required.update(CAPACITY_SCHEMAS)
    if schema_at_least(schema_version, (1, 2)):
        required.update(DURATION_SCHEMAS)
        required.update(ROOT_GUARD_SCHEMAS)
        if not (cli.parent / "root_role_guard.py").is_file():
            raise BridgeError("CLI_INCOMPATIBLE", "schema 1.2 root-role guard is missing")
    if schema_at_least(schema_version, (1, 3)):
        required.update(LIFECYCLE_SCHEMAS)
    if schema_at_least(schema_version, (1, 4)):
        required.update(FEDERATION_SCHEMAS)
        required.update(LEGACY_ARCHIVE_SCHEMAS)
    validate_schema_files(cli.parent, required)
    rules = status.get("rules")
    if not isinstance(rules, list):
        raise BridgeError("MACHINE_RESPONSE_INVALID", "status rules must be an array")
    quarantined = sorted(
        rule.get("id", "unknown")
        for rule in rules
        if isinstance(rule, dict) and rule.get("state") == "quarantined"
    )
    if quarantined:
        raise BridgeError(
            "POLICY_CONFLICT_QUARANTINED",
            "quarantined policy rules require orchestrator reconciliation",
            exit_status=3,
            details={"rule_ids": quarantined},
        )
    return {
        "cli_version": version,
        "schema_version": status["schema_version"],
        "policy_revision": status.get("policy_revision"),
        "state_revision": status.get("revision"),
        "quarantined_rule_ids": [],
    }


def validate_prepare_result(result: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    if set(result) != {"envelope", "prompt", "outbox"}:
        raise BridgeError("MACHINE_RESPONSE_INVALID", "prepare-launch result fields are incompatible")
    envelope = result["envelope"]
    prompt = result["prompt"]
    outbox = result["outbox"]
    if not isinstance(envelope, dict) or not isinstance(prompt, str) or not isinstance(outbox, dict):
        raise BridgeError("MACHINE_RESPONSE_INVALID", "prepare-launch result types are incompatible")
    required = {
        "envelope_version",
        "task_id",
        "issued_at",
        "policy_snapshot_revision",
        "lease_epoch",
        "fencing_token",
        "effective_rules",
        "runtime_policy",
        "receipt_required",
    }
    if not required.issubset(envelope):
        raise BridgeError("MACHINE_RESPONSE_INVALID", "launch envelope is incomplete")
    if envelope["envelope_version"] != INTERFACE_VERSION:
        raise BridgeError("INTERFACE_INCOMPATIBLE", "launch envelope version is incompatible")
    if outbox.get("kind") != "CREATE_THREAD" or not isinstance(outbox.get("outbox_id"), str):
        raise BridgeError("MACHINE_RESPONSE_INVALID", "launch outbox is incompatible")
    rules = envelope["effective_rules"]
    if not isinstance(rules, list) or not rules:
        raise BridgeError("MACHINE_RESPONSE_INVALID", "launch envelope must carry effective rules")
    rule_ids = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise BridgeError("MACHINE_RESPONSE_INVALID", "effective rule entry is incompatible")
        rule_id = rule.get("rule_id", rule.get("id"))
        if not isinstance(rule_id, str):
            raise BridgeError("MACHINE_RESPONSE_INVALID", "effective rule entry is incompatible")
        rule_ids.append(rule_id)
    required_receipt = envelope["receipt_required"]
    if not isinstance(required_receipt, dict):
        raise BridgeError("MACHINE_RESPONSE_INVALID", "receipt_required must be an object")
    echoes = {
        "policy_snapshot_revision": envelope["policy_snapshot_revision"],
        "lease_epoch": envelope["lease_epoch"],
        "fencing_token": envelope["fencing_token"],
    }
    for key, value in echoes.items():
        if required_receipt.get(key) != value:
            raise BridgeError("MACHINE_RESPONSE_INVALID", f"receipt echo mismatch: {key}")
    if sorted(required_receipt.get("applicable_rule_ids", [])) != sorted(rule_ids):
        raise BridgeError("MACHINE_RESPONSE_INVALID", "receipt rule IDs do not match envelope")
    if "duration_estimate" in envelope and required_receipt.get(
        "duration_estimate"
    ) != envelope["duration_estimate"]:
        raise BridgeError(
            "MACHINE_RESPONSE_INVALID",
            "receipt duration estimate does not match envelope",
        )
    runtime_policy = required_receipt.get("runtime_policy")
    if runtime_policy != RUNTIME_POLICY_REQUIRED:
        raise BridgeError(
            "RUNTIME_POLICY_INCOMPATIBLE",
            "launch receipt runtime policy is incompatible",
        )
    envelope_runtime = envelope["runtime_policy"]
    if not isinstance(envelope_runtime, dict):
        raise BridgeError(
            "RUNTIME_POLICY_INCOMPATIBLE",
            "launch envelope runtime policy is malformed",
        )
    if (
        envelope_runtime.get("root", {}).get("model")
        != RUNTIME_POLICY_REQUIRED["root_model"]
        or envelope_runtime.get("root", {}).get("reasoning_effort")
        != RUNTIME_POLICY_REQUIRED["root_reasoning_effort"]
        or envelope_runtime.get("root", {}).get("service_tier")
        != RUNTIME_POLICY_REQUIRED["root_service_tier"]
        or envelope_runtime.get("root", {}).get("fast_mode") is not True
        or envelope_runtime.get("worker_defaults", {}).get("model")
        != RUNTIME_POLICY_REQUIRED["worker_model"]
        or envelope_runtime.get("worker_defaults", {}).get("reasoning_effort")
        != RUNTIME_POLICY_REQUIRED["worker_reasoning_effort"]
        or envelope_runtime.get("worker_defaults", {}).get("service_tier")
        != RUNTIME_POLICY_REQUIRED["worker_service_tier"]
        or envelope_runtime.get("worker_defaults", {}).get("fast_mode") is not True
    ):
        raise BridgeError(
            "RUNTIME_POLICY_INCOMPATIBLE",
            "launch envelope root or worker runtime policy drifted",
        )
    return envelope, sorted(rule_ids)


def validate_capacity_result(
    result: dict[str, Any], request: dict[str, Any]
) -> None:
    expected_fields = {
        "request_id",
        "previous_configured_capacity",
        "configured_capacity",
        "previous_state_revision",
        "committed_state_revision",
        "active_or_reserved_count_at_commit",
        "replayed",
        "current_configured_capacity",
        "current_state_revision",
    }
    if set(result) != expected_fields:
        raise BridgeError(
            "MACHINE_RESPONSE_INVALID",
            "configure-capacity result fields are incompatible",
        )
    integer_fields = expected_fields - {"request_id", "replayed"}
    if any(
        isinstance(result[field], bool) or not isinstance(result[field], int)
        for field in integer_fields
    ):
        raise BridgeError(
            "MACHINE_RESPONSE_INVALID",
            "configure-capacity result integer fields are incompatible",
        )
    if (
        result["request_id"] != request.get("request_id")
        or result["previous_configured_capacity"]
        != request.get("expected_configured_capacity")
        or result["configured_capacity"]
        != request.get("requested_configured_capacity")
        or result["previous_state_revision"]
        != request.get("expected_state_revision")
        or result["committed_state_revision"]
        != result["previous_state_revision"] + 1
        or result["active_or_reserved_count_at_commit"] < 0
        or result["active_or_reserved_count_at_commit"]
        > result["configured_capacity"]
        or not 1 <= result["current_configured_capacity"] <= 64
        or result["current_state_revision"]
        < result["committed_state_revision"]
        or not isinstance(result["replayed"], bool)
    ):
        raise BridgeError(
            "MACHINE_RESPONSE_INVALID",
            "configure-capacity result does not match the typed request",
        )


def validate_runtime_attestation(value: Any) -> dict[str, Any]:
    expected_fields = {
        "root_model",
        "root_reasoning_effort",
        "root_service_tier",
        "root_fast_mode",
        "worker_model",
        "worker_reasoning_effort",
        "worker_service_tier",
        "worker_fast_mode",
        "service_tier_attestation",
        "tier_provenance",
        "auth_mode",
        "history_mode",
        "parent_attestation_present",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise BridgeError(
            "RUNTIME_ATTESTATION_INVALID",
            "runtime attestation fields are incompatible",
            exit_status=2,
        )
    if value["auth_mode"] != "subscription":
        raise BridgeError(
            "FAST_AUTH_MODE_UNSUPPORTED",
            "Subscription priority-tier semantics cannot be claimed for API-key auth",
            exit_status=2,
        )
    exact = {
        "root_model": RUNTIME_POLICY_REQUIRED["root_model"],
        "root_reasoning_effort": RUNTIME_POLICY_REQUIRED[
            "root_reasoning_effort"
        ],
        "root_service_tier": RUNTIME_POLICY_REQUIRED["root_service_tier"],
        "root_fast_mode": True,
        "worker_model": RUNTIME_POLICY_REQUIRED["worker_model"],
        "worker_reasoning_effort": RUNTIME_POLICY_REQUIRED[
            "worker_reasoning_effort"
        ],
        "worker_service_tier": RUNTIME_POLICY_REQUIRED["worker_service_tier"],
        "worker_fast_mode": True,
        "parent_attestation_present": True,
    }
    if any(value.get(key) != expected for key, expected in exact.items()):
        raise BridgeError(
            "RUNTIME_ATTESTATION_INVALID",
            "root or worker runtime attestation drifted",
            exit_status=2,
        )
    source = value["service_tier_attestation"]
    expected_provenance = {
        "runtime": "platform-runtime",
        "config-verified": "trusted-project-and-user-config",
    }.get(source)
    if expected_provenance is None:
        raise BridgeError(
            "SERVICE_TIER_UNATTESTED",
            "effective fast tier is not verified",
            exit_status=2,
        )
    if value["tier_provenance"] != expected_provenance:
        raise BridgeError(
            "SERVICE_TIER_PROVENANCE_INVALID",
            "service-tier provenance contradicts its verification source",
            exit_status=2,
        )
    if value["history_mode"] not in {"none", "bounded", "full-history"}:
        raise BridgeError(
            "RUNTIME_ATTESTATION_INVALID",
            "history mode is incompatible",
            exit_status=2,
        )
    scan_strings(value, durable=True)
    return value


def ensure_ticket_parent(ticket_path: Path) -> None:
    parent = ticket_path.parent
    validate_private_dir(str(parent), "ticket directory")
    if ticket_path.exists():
        raise BridgeError("TICKET_EXISTS", "ticket path already exists", exit_status=3)


def write_ticket_new(path: Path, ticket: dict[str, Any]) -> None:
    ensure_ticket_parent(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(canonical(ticket) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def load_ticket(path_value: str) -> tuple[Path, dict[str, Any]]:
    path = require_absolute(path_value, "ticket")
    if not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise BridgeError("RECEIPT_INVALID", "ticket must be a private 0600 file", exit_status=2)
    if hasattr(os, "getuid") and path.stat().st_uid != os.getuid():
        raise BridgeError("RECEIPT_INVALID", "ticket owner mismatch", exit_status=2)
    try:
        ticket = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeError("RECEIPT_INVALID", "ticket is not valid JSON", exit_status=2) from exc
    legacy_expected = {
        "ticket_version",
        "task_id",
        "source_event_key",
        "outcome_key",
        "issued_at",
        "receipt_deadline",
        "lease_expires_at",
        "policy_snapshot_revision",
        "lease_epoch",
        "fencing_token",
        "applicable_rule_ids",
        "outbox",
        "receipt",
        "last_heartbeat_at",
        "handback",
    }
    current_expected = legacy_expected | {
        "control_schema_version",
        "duration_estimate",
        "owner_claim_id",
    }
    current_expected_with_runtime = current_expected | {"runtime_policy"}
    if not isinstance(ticket, dict) or frozenset(ticket) not in {
        frozenset(legacy_expected),
        frozenset(current_expected),
        frozenset(current_expected_with_runtime),
    }:
        raise BridgeError("RECEIPT_INVALID", "ticket fields are incompatible", exit_status=2)
    if ticket["ticket_version"] == "1.0" and set(ticket) == legacy_expected:
        ticket["control_schema_version"] = "1.0"
        ticket["duration_estimate"] = None
        ticket["owner_claim_id"] = None
    if (
        ticket["ticket_version"] in LEGACY_TICKET_VERSIONS
        and set(ticket) == current_expected
    ):
        if ticket["receipt"] is not None:
            raise BridgeError(
                "RUNTIME_ATTESTATION_MISSING",
                "legacy receipted ticket cannot be promoted without runtime attestation",
                exit_status=2,
            )
        ticket["ticket_version"] = TICKET_VERSION
        ticket["runtime_policy"] = RUNTIME_POLICY_REQUIRED
    elif (
        ticket["ticket_version"] != TICKET_VERSION
        or set(ticket) != current_expected_with_runtime
        or ticket["runtime_policy"] != RUNTIME_POLICY_REQUIRED
    ):
        raise BridgeError("INTERFACE_INCOMPATIBLE", "ticket version is incompatible", exit_status=2)
    if not isinstance(ticket["task_id"], str) or not isinstance(ticket["applicable_rule_ids"], list):
        raise BridgeError("RECEIPT_INVALID", "ticket identity is malformed", exit_status=2)
    scan_strings(ticket, durable=True)
    return path, ticket


def require_missing_legacy_transport_ticket(
    state_dir: Path,
    task_id: str,
    external_thread_id: str,
    *,
    now: str,
) -> dict[str, Any]:
    """Prove one legacy task has no matching private transport ticket."""

    if ID_RE.fullmatch(task_id) is None or ID_RE.fullmatch(external_thread_id) is None:
        raise BridgeError(
            "LEGACY_ARCHIVE_IDENTITY_INVALID",
            "legacy archive task identity must use stable identifiers",
            exit_status=2,
        )
    try:
        tickets = list(state_dir.glob("*.ticket.json"))
    except OSError as exc:
        raise BridgeError(
            "LEGACY_TICKET_AUTHORITY_UNSAFE",
            "legacy transport ticket authority is unreadable",
            exit_status=4,
        ) from exc
    if len(tickets) > MAX_LEGACY_TICKETS:
        raise BridgeError(
            "LEGACY_TICKET_AUTHORITY_UNSAFE",
            "legacy transport ticket scan exceeds its bounded authority",
            exit_status=4,
        )

    exact_matches = 0
    for path in tickets:
        try:
            metadata = path.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_size > MAX_REQUEST_BYTES
                or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
            ):
                raise ValueError("unsafe ticket metadata")

            def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                value: dict[str, Any] = {}
                for key, child in pairs:
                    if key in value:
                        raise ValueError("duplicate ticket key")
                    value[key] = child
                return value

            ticket = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=no_duplicate_keys,
            )
            if not isinstance(ticket, dict):
                raise ValueError("ticket is not an object")
            ticket_task_id = ticket.get("task_id")
            if (
                not isinstance(ticket_task_id, str)
                or ID_RE.fullmatch(ticket_task_id) is None
                or "receipt" not in ticket
            ):
                raise ValueError("ticket identity is malformed")
            receipt = ticket["receipt"]
            ticket_external_id = None
            if receipt is not None:
                if not isinstance(receipt, dict):
                    raise ValueError("ticket receipt is malformed")
                ticket_external_id = receipt.get("external_thread_id")
                if (
                    not isinstance(ticket_external_id, str)
                    or ID_RE.fullmatch(ticket_external_id) is None
                ):
                    raise ValueError("ticket receipt identity is malformed")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise BridgeError(
                "LEGACY_TICKET_AUTHORITY_UNSAFE",
                "legacy transport ticket authority is malformed or unsafe",
                exit_status=4,
            ) from exc

        task_matches = ticket_task_id == task_id
        external_matches = ticket_external_id == external_thread_id
        if task_matches != external_matches:
            raise BridgeError(
                "LEGACY_TICKET_IDENTITY_MISMATCH",
                "legacy transport ticket matches only part of the canonical identity",
                exit_status=3,
            )
        if task_matches and external_matches:
            exact_matches += 1

    if exact_matches:
        raise BridgeError(
            "LEGACY_TICKET_PRESENT",
            "matching transport ticket exists; use the normal archive receipt route",
            exit_status=3,
        )
    return {
        "task_id": task_id,
        "external_thread_id": external_thread_id,
        "state": "missing",
        "verified_at": now,
        "scanned_ticket_count": len(tickets),
        "matching_ticket_count": 0,
    }


def classify_stale_present_transport_ticket(
    state_dir: Path,
    task_id: str,
    external_thread_id: str,
    *,
    now: str,
) -> dict[str, Any]:
    """Bind one exact private ticket, or report missing for replay only."""

    if ID_RE.fullmatch(task_id) is None or ID_RE.fullmatch(external_thread_id) is None:
        raise BridgeError(
            "LEGACY_ARCHIVE_IDENTITY_INVALID",
            "stale-present archive identity must use stable identifiers",
            exit_status=2,
        )
    try:
        ticket_paths = list(state_dir.glob("*.ticket.json"))
    except OSError as exc:
        raise BridgeError(
            "LEGACY_TICKET_AUTHORITY_UNSAFE",
            "legacy transport ticket authority is unreadable",
            exit_status=4,
        ) from exc
    if len(ticket_paths) > MAX_LEGACY_TICKETS:
        raise BridgeError(
            "LEGACY_TICKET_AUTHORITY_UNSAFE",
            "legacy transport ticket scan exceeds its bounded authority",
            exit_status=4,
        )

    exact: list[dict[str, Any]] = []
    for path in ticket_paths:
        descriptor = -1
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
            metadata = os.fstat(descriptor)
            path_metadata = path.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or not stat.S_ISREG(path_metadata.st_mode)
                or metadata.st_dev != path_metadata.st_dev
                or metadata.st_ino != path_metadata.st_ino
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_size < 1
                or metadata.st_size > MAX_REQUEST_BYTES
                or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
            ):
                raise ValueError("unsafe ticket metadata")
            chunks: list[bytes] = []
            remaining = metadata.st_size + 1
            while remaining:
                chunk = os.read(descriptor, min(65_536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) != metadata.st_size:
                raise ValueError("ticket size changed during read")

            def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                decoded: dict[str, Any] = {}
                for key, child in pairs:
                    if key in decoded:
                        raise ValueError("duplicate ticket key")
                    decoded[key] = child
                return decoded

            ticket = json.loads(raw, object_pairs_hook=no_duplicate_keys)
            if not isinstance(ticket, dict):
                raise ValueError("ticket is not an object")
            ticket_task_id = ticket.get("task_id")
            if (
                not isinstance(ticket_task_id, str)
                or ID_RE.fullmatch(ticket_task_id) is None
                or "receipt" not in ticket
            ):
                raise ValueError("ticket identity is malformed")
            receipt = ticket["receipt"]
            ticket_external_id = None
            if receipt is not None:
                if not isinstance(receipt, dict):
                    raise ValueError("ticket receipt is malformed")
                ticket_external_id = receipt.get("external_thread_id")
                if (
                    not isinstance(ticket_external_id, str)
                    or ID_RE.fullmatch(ticket_external_id) is None
                ):
                    raise ValueError("ticket receipt identity is malformed")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise BridgeError(
                "LEGACY_TICKET_AUTHORITY_UNSAFE",
                "legacy transport ticket authority is malformed or unsafe",
                exit_status=4,
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

        task_matches = ticket_task_id == task_id
        external_matches = ticket_external_id == external_thread_id
        if task_matches != external_matches:
            raise BridgeError(
                "LEGACY_TICKET_IDENTITY_MISMATCH",
                "transport ticket matches only part of the canonical identity",
                exit_status=3,
            )
        if task_matches and external_matches:
            exact.append(
                {
                    "ticket_filename": path.name,
                    "ticket_sha256": hashlib.sha256(raw).hexdigest(),
                    "ticket_size": metadata.st_size,
                    "ticket_device": metadata.st_dev,
                    "ticket_inode": metadata.st_ino,
                }
            )

    if len(exact) > 1:
        raise BridgeError(
            "LEGACY_TICKET_DUPLICATE",
            "multiple transport tickets match the canonical task identity",
            exit_status=3,
        )
    common = {
        "task_id": task_id,
        "external_thread_id": external_thread_id,
        "verified_at": now,
        "scanned_ticket_count": len(ticket_paths),
    }
    if not exact:
        return {
            **common,
            "state": "missing",
            "matching_ticket_count": 0,
        }
    return {
        **common,
        "state": "stale-present",
        "matching_ticket_count": 1,
        **exact[0],
    }


def remove_committed_stale_ticket(
    state_dir: Path,
    proof: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """Remove only the exact committed ticket; leave drift untouched."""

    if proof.get("state") == "missing":
        return
    filename = proof.get("ticket_filename")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise BridgeError(
            "LEGACY_TICKET_PATH_INVALID",
            "committed cleanup ticket path is invalid",
            exit_status=4,
        )
    path = state_dir / filename
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        path_metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not stat.S_ISREG(path_metadata.st_mode)
            or metadata.st_dev != path_metadata.st_dev
            or metadata.st_ino != path_metadata.st_ino
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_dev != proof.get("ticket_device")
            or metadata.st_ino != proof.get("ticket_inode")
            or metadata.st_size != proof.get("ticket_size")
            or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
        ):
            raise ValueError("ticket metadata drifted")
        chunks: list[bytes] = []
        remaining = metadata.st_size + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if (
            len(raw) != metadata.st_size
            or hashlib.sha256(raw).hexdigest() != proof.get("ticket_sha256")
            or result.get("transport_ticket_filename") != filename
            or result.get("transport_ticket_sha256")
            != proof.get("ticket_sha256")
        ):
            raise ValueError("ticket content drifted")
        final_metadata = path.lstat()
        if (
            not stat.S_ISREG(final_metadata.st_mode)
            or final_metadata.st_dev != metadata.st_dev
            or final_metadata.st_ino != metadata.st_ino
            or final_metadata.st_size != metadata.st_size
            or stat.S_IMODE(final_metadata.st_mode) != 0o600
        ):
            raise ValueError("ticket path drifted before unlink")
        path.unlink()
        directory_descriptor = os.open(
            state_dir,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except (OSError, ValueError) as exc:
        raise BridgeError(
            "LEGACY_TICKET_POSTCOMMIT_CLEANUP_FAILED",
            "authoritative archive committed but exact ticket cleanup failed; replay safely",
            exit_status=4,
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def replace_ticket(path: Path, ticket: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".ticket-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(canonical(ticket) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def require_fresh_unreceipted(ticket: dict[str, Any], now: str) -> None:
    if ticket["receipt"] is not None:
        raise BridgeError("RECEIPT_CONFLICT", "launch receipt already recorded", exit_status=3)
    if parse_time(now) > parse_time(ticket["receipt_deadline"]):
        raise BridgeError("RECEIPT_STALE", "launch receipt deadline expired", exit_status=2)


def require_unreceipted_setup_ticket(ticket: dict[str, Any], now: str) -> None:
    """Allow exact setup rollback both before and after receipt expiry."""

    parse_time(now)
    if ticket["receipt"] is not None:
        raise BridgeError(
            "RECEIPT_CONFLICT", "launch receipt already recorded", exit_status=3
        )
    handback = ticket.get("handback")
    if handback is not None and (
        not isinstance(handback, dict)
        or set(handback) != {"recorded_at", "state"}
        or handback.get("state") != "FAILED"
    ):
        raise BridgeError(
            "SETUP_FAILURE_REPLAY_CONFLICT",
            "setup failure ticket has a different terminal state",
            exit_status=3,
        )


def require_committed_receipt(ticket: dict[str, Any]) -> dict[str, Any]:
    receipt = ticket.get("receipt")
    if not isinstance(receipt, dict) or set(receipt) != {
        "external_thread_id",
        "recorded_at",
        "runtime_attestation",
    }:
        raise BridgeError("RECEIPT_MISSING", "committed exact launch receipt is required", exit_status=2)
    return receipt


def require_active_receipt(ticket: dict[str, Any], now: str) -> None:
    require_committed_receipt(ticket)
    if parse_time(now) >= parse_time(ticket["lease_expires_at"]):
        raise BridgeError("RECEIPT_STALE", "worker lease expired; takeover or reconcile", exit_status=2)


def require_external_identity(ticket: dict[str, Any], external_thread_id: str) -> None:
    receipt = ticket.get("receipt")
    if not isinstance(receipt, dict):
        raise BridgeError("RECEIPT_MISSING", "committed exact launch receipt is required", exit_status=2)
    if receipt.get("external_thread_id") != external_thread_id:
        raise BridgeError(
            "EXTERNAL_MIRROR_STOP",
            "only the canonical receipt-backed external task may mutate",
            exit_status=3,
            details={
                "required_actions": [
                    "STOP_READ_ONLY",
                    "RETURN_ZERO_CHANGE_HANDBACK",
                    "ARCHIVE_EXTERNAL_MIRROR",
                ]
            },
        )


def authoritative_archive_saga(
    status: dict[str, Any], task_id: str, local_saga: dict[str, Any]
) -> dict[str, Any] | None:
    """Resolve one setup-failed reservation to its exact receipted replacement."""

    saga_id = local_saga.get("saga_id")
    reserved_task_ids = local_saga.get("reserved_task_ids")
    events = local_saga.get("events")
    if (
        not isinstance(saga_id, str)
        or local_saga.get("predecessor_task_id") != task_id
        or local_saga.get("outcome") != "SUCCESSOR_RESERVED"
        or not isinstance(reserved_task_ids, list)
        or len(reserved_task_ids) != 1
        or not isinstance(reserved_task_ids[0], str)
        or local_saga.get("receipted_task_ids") != []
        or not isinstance(events, list)
    ):
        return None
    failed_task_id = reserved_task_ids[0]
    reservations = [
        event
        for event in events
        if isinstance(event, dict)
        and event.get("event") == "SUCCESSOR_RESERVED"
        and isinstance(event.get("metadata"), dict)
        and event["metadata"].get("task_id") == failed_task_id
    ]
    if len(reservations) != 1:
        return None

    capacity = status.get("capacity")
    if not isinstance(capacity, list):
        return None
    matching = [
        saga
        for saga in capacity
        if isinstance(saga, dict) and saga.get("saga_id") == saga_id
    ]
    if len(matching) != 1:
        return None
    saga = matching[0]
    if (
        saga.get("outcome") not in ARCHIVE_CONTROL_OUTCOMES
        or saga.get("clean_handback") is not True
        or saga.get("failure_state")
        not in {None, "CAPACITY_INVARIANT_FAILED"}
    ):
        return None
    if saga["outcome"] != "SUCCESSOR_RECEIPTED":
        return None

    replacement_task_id = saga.get("successor_task_id")
    if (
        not isinstance(replacement_task_id, str)
        or replacement_task_id == failed_task_id
        or saga.get("successor_receipted") is not True
    ):
        return None

    tasks = status.get("tasks")
    outbox = status.get("outbox")
    if not isinstance(tasks, list) or not isinstance(outbox, list):
        return None
    failed = [
        item
        for item in tasks
        if isinstance(item, dict) and item.get("task_id") == failed_task_id
    ]
    replacement = [
        item
        for item in tasks
        if isinstance(item, dict) and item.get("task_id") == replacement_task_id
    ]
    failed_create = [
        item
        for item in outbox
        if isinstance(item, dict)
        and item.get("task_id") == failed_task_id
        and item.get("kind") == "CREATE_THREAD"
    ]
    replacement_create = [
        item
        for item in outbox
        if isinstance(item, dict)
        and item.get("task_id") == replacement_task_id
        and item.get("kind") == "CREATE_THREAD"
    ]
    if (
        len(failed) != 1
        or failed[0].get("state") != "FAILED"
        or failed[0].get("canonical_external_thread_id") is not None
        or failed[0].get("receipt_fence") is not None
        or len(failed_create) != 1
        or str(failed_create[0].get("state", "")).lower() != "poisoned"
        or len(replacement) != 1
        or len(replacement_create) != 1
        or str(replacement_create[0].get("state", "")).lower() != "completed"
    ):
        return None

    successor = replacement[0]
    successor_state = successor.get("state")
    external_thread_id = successor.get("canonical_external_thread_id")
    receipt_fence = successor.get("receipt_fence")
    fence_fields = {
        "task_id",
        "receipt_external_thread_id",
        "policy_snapshot_revision",
        "lease_epoch",
        "lease_expires_at",
        "fencing_token",
        "owner_claim_id",
        "owner_claim_status",
        "claim_lease_epoch",
        "claim_fencing_token",
    }
    if (
        successor_state not in {"RUNNING", "ARCHIVE_PENDING", "ARCHIVED"}
        or not isinstance(external_thread_id, str)
        or not isinstance(receipt_fence, dict)
        or not fence_fields.issubset(receipt_fence)
        or receipt_fence.get("task_id") != replacement_task_id
        or receipt_fence.get("receipt_external_thread_id") != external_thread_id
        or receipt_fence.get("claim_lease_epoch") != receipt_fence.get("lease_epoch")
        or receipt_fence.get("claim_fencing_token")
        != receipt_fence.get("fencing_token")
    ):
        return None

    terminal_successor = successor_state in {"ARCHIVE_PENDING", "ARCHIVED"}
    expected_claim_status = "released" if terminal_successor else "active"
    if receipt_fence.get("owner_claim_status") != expected_claim_status:
        return None
    if saga.get("failure_state") is not None and not terminal_successor:
        return None
    if terminal_successor:
        lifecycle = successor.get("lifecycle")
        archive = [
            item
            for item in outbox
            if isinstance(item, dict)
            and item.get("task_id") == replacement_task_id
            and item.get("kind") == "ARCHIVE_THREAD"
        ]
        expected_archive_state = (
            "completed" if successor_state == "ARCHIVED" else "pending"
        )
        if (
            not isinstance(lifecycle, dict)
            or lifecycle.get("task_id") != replacement_task_id
            or lifecycle.get("lifecycle_state") != "COMPLETED"
            or lifecycle.get("worker_status") != "completed"
            or lifecycle.get("required_action") != "ARCHIVE"
            or len(archive) != 1
            or str(archive[0].get("state", "")).lower()
            != expected_archive_state
        ):
            return None
    return saga


def require_refill_saga_before_archive(
    state_dir: Path,
    task_id: str,
    *,
    status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ledger_path = state_dir / "pm-proxy-refill-ledger.json"
    if not ledger_path.is_file() or ledger_path.is_symlink():
        raise BridgeError(
            "CAPACITY_SAGA_MISSING",
            "closure/refill saga must complete before archive",
            exit_status=2,
        )
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeError("REFILL_LEDGER_CORRUPT", "refill ledger is invalid") from exc
    if (
        not isinstance(ledger, dict)
        or ledger.get("schema_version") != "1.0"
        or not isinstance(ledger.get("sagas"), dict)
    ):
        raise BridgeError("REFILL_LEDGER_CORRUPT", "refill ledger is incompatible")
    matching = [
        saga
        for saga in ledger["sagas"].values()
        if isinstance(saga, dict) and saga.get("predecessor_task_id") == task_id
    ]
    if len(matching) != 1:
        raise BridgeError(
            "CAPACITY_SAGA_MISSING",
            "exact predecessor refill saga is required",
            exit_status=2,
        )
    saga = matching[0]
    if not isinstance(saga.get("archive_outbox_id"), str):
        raise BridgeError(
            "CAPACITY_SAGA_MISSING",
            "exact predecessor archive outbox is required",
            exit_status=2,
        )
    if saga.get("outcome") not in ARCHIVE_LOCAL_OUTCOMES:
        authoritative = (
            None
            if status is None
            else authoritative_archive_saga(status, task_id, saga)
        )
        if authoritative is not None:
            return saga
        raise BridgeError(
            "CAPACITY_REFILL_PENDING",
            "successor receipt or durable empty/owner-gated/full evidence is required",
            exit_status=2,
            details={"outcome": saga.get("outcome")},
        )
    return saga


def require_terminal_archive_admission(
    status: dict[str, Any],
    ticket: dict[str, Any],
    saga: dict[str, Any],
    *,
    expired: bool,
) -> None:
    """Admit only an exact durable terminal predecessor after receipt expiry."""

    receipt = require_committed_receipt(ticket)
    handback = ticket.get("handback")
    if not isinstance(handback, dict) or handback.get("state") != "ARCHIVE_PENDING":
        raise BridgeError(
            "RECEIPT_STALE",
            "expired receipt has no exact terminal archive admission",
            exit_status=2,
        )
    permitted_handback_fields = {"recorded_at", "state", "archive_receipt_at"}
    if (
        not isinstance(handback.get("recorded_at"), str)
        or not set(handback).issubset(permitted_handback_fields)
    ):
        raise BridgeError(
            "RECEIPT_STALE",
            "expired receipt has no exact terminal archive admission",
            exit_status=2,
        )
    matching = [
        task
        for task in status.get("tasks", [])
        if isinstance(task, dict) and task.get("task_id") == ticket["task_id"]
    ]
    if len(matching) != 1:
        raise BridgeError(
            "RECEIPT_STALE",
            "expired receipt task identity is no longer authoritative",
            exit_status=2,
        )
    task = matching[0]
    replay = task.get("state") == "ARCHIVED"
    expected_state = "ARCHIVED" if replay else "ARCHIVE_PENDING"
    lifecycle = task.get("lifecycle")
    exact_disposition = (
        task.get("terminal_disposition") in EXPIRED_ARCHIVE_DISPOSITIONS
    )
    if task.get("terminal_disposition") == "superseded":
        exact_disposition = (
            authoritative_archive_saga(status, ticket["task_id"], saga) is not None
        )
    expected_fence = {
        "task_id": ticket["task_id"],
        "receipt_external_thread_id": receipt["external_thread_id"],
        "policy_snapshot_revision": ticket["policy_snapshot_revision"],
        "lease_epoch": ticket["lease_epoch"],
        "lease_expires_at": ticket["lease_expires_at"],
        "fencing_token": ticket["fencing_token"],
        "owner_claim_id": ticket["owner_claim_id"],
        "owner_claim_status": "released",
        "claim_lease_epoch": ticket["lease_epoch"],
        "claim_fencing_token": ticket["fencing_token"],
    }
    exact_task = (
        task.get("state") == expected_state
        and task.get("source_event_key") == ticket["source_event_key"]
        and task.get("canonical_external_thread_id")
        == receipt["external_thread_id"]
        and isinstance(task.get("receipt_fence"), dict)
        and set(task["receipt_fence"]) == set(expected_fence)
        and task["receipt_fence"] == expected_fence
        and isinstance(lifecycle, dict)
        and lifecycle.get("task_id") == ticket["task_id"]
        and lifecycle.get("lifecycle_state") == "COMPLETED"
        and lifecycle.get("worker_status") == "completed"
        and lifecycle.get("required_action") == "ARCHIVE"
    )
    if expired:
        exact_task = exact_task and exact_disposition
    if not exact_task:
        raise BridgeError(
            "RECEIPT_STALE",
            "expired receipt terminal identity does not match authority",
            exit_status=2,
        )
    if replay != isinstance(handback.get("archive_receipt_at"), str):
        raise BridgeError(
            "RECEIPT_STALE",
            "archive replay state does not match the exact ticket",
            exit_status=2,
        )
    archive_outbox = [
        item
        for item in status.get("outbox", [])
        if isinstance(item, dict)
        and item.get("task_id") == ticket["task_id"]
        and item.get("kind") == "ARCHIVE_THREAD"
    ]
    expected_outbox_state = "completed" if replay else "pending"
    if (
        len(archive_outbox) != 1
        or archive_outbox[0].get("outbox_id") != saga["archive_outbox_id"]
        or str(archive_outbox[0].get("state", "")).lower()
        != expected_outbox_state
    ):
        raise BridgeError(
            "RECEIPT_STALE",
            "archive outbox does not match the exact terminal ticket",
            exit_status=2,
        )


def inject_ticket_fields(request: dict[str, Any], ticket: dict[str, Any]) -> None:
    expected = {
        "task_id": ticket["task_id"],
        "policy_snapshot_revision": ticket["policy_snapshot_revision"],
        "lease_epoch": ticket["lease_epoch"],
        "fencing_token": ticket["fencing_token"],
    }
    for key, value in expected.items():
        if key in request and request[key] != value:
            raise BridgeError("RECEIPT_MISMATCH", f"request does not match ticket: {key}", exit_status=2)
        request[key] = value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", required=True, help="Absolute Firestarter orchestrator_control.py")
    parser.add_argument("--state-dir", required=True, help="Absolute initialized private state directory")
    sub = parser.add_subparsers(dest="operation", required=True)

    sub.add_parser("doctor")
    init_parser = sub.add_parser("init")
    init_parser.add_argument("--now", required=True)

    for name in (
        "record-policy-rule",
        "effective-rules",
        "classify-decision",
        "recycle-queue",
        "duration-estimate",
        "duration-schedule",
        "record-dispatcher-adoption",
        "configure-capacity",
    ):
        request_parser = sub.add_parser(name)
        request_parser.add_argument("--request", required=True)
    root_action = sub.add_parser("root-action")
    root_action.add_argument("--request", required=True)

    prepare = sub.add_parser("prepare-launch")
    prepare.add_argument("--recycle-request", required=True)
    prepare.add_argument("--launch-request", required=True)
    prepare.add_argument("--ticket", required=True)

    receipt = sub.add_parser("record-launch-receipt")
    receipt.add_argument("--ticket", required=True)
    receipt.add_argument("--external-thread-id", required=True)
    receipt.add_argument("--runtime-attestation", required=True)
    receipt.add_argument("--request-id", required=True)
    receipt.add_argument("--now", required=True)

    external = sub.add_parser("reconcile-external-task")
    external.add_argument("--ticket", required=True)
    external.add_argument("--external-thread-id", required=True)
    external.add_argument("--request-id", required=True)
    external.add_argument("--now", required=True)

    heartbeat = sub.add_parser("heartbeat")
    heartbeat.add_argument("--ticket", required=True)
    heartbeat.add_argument("--external-thread-id", required=True)
    heartbeat.add_argument("--request-id", required=True)
    heartbeat.add_argument("--lease-expires-at", required=True)
    heartbeat.add_argument("--now", required=True)

    handback = sub.add_parser("record-handback")
    handback.add_argument("--ticket", required=True)
    handback.add_argument("--external-thread-id", required=True)
    handback.add_argument("--request", required=True)

    lifecycle = sub.add_parser("lifecycle-watchdog")
    lifecycle.add_argument("--ticket", required=True)
    lifecycle.add_argument("--external-thread-id", required=True)
    lifecycle.add_argument("--request", required=True)
    lifecycle.add_argument("--successor-ticket")

    decision_route = sub.add_parser("route-owner-decision")
    decision_route.add_argument("--ticket", required=True)
    decision_route.add_argument("--external-thread-id", required=True)
    decision_route.add_argument("--request", required=True)

    acknowledge_hold = sub.add_parser("acknowledge-control-schema-hold")
    acknowledge_hold.add_argument("--ticket", required=True)
    acknowledge_hold.add_argument("--external-thread-id", required=True)
    acknowledge_hold.add_argument("--request", required=True)

    duration_progress = sub.add_parser("record-duration-progress")
    duration_progress.add_argument("--ticket", required=True)
    duration_progress.add_argument("--external-thread-id", required=True)
    duration_progress.add_argument("--request", required=True)

    duration_observation = sub.add_parser("record-duration-observation")
    duration_observation.add_argument("--ticket", required=True)
    duration_observation.add_argument("--external-thread-id", required=True)
    duration_observation.add_argument("--request", required=True)

    setup_failure = sub.add_parser("record-setup-failure")
    setup_failure.add_argument("--ticket", required=True)
    setup_failure.add_argument("--successor-ticket")
    setup_failure.add_argument("--request", required=True)

    takeover = sub.add_parser("takeover-lease")
    takeover.add_argument("--ticket", required=True)
    takeover.add_argument("--request", required=True)

    expired = sub.add_parser("reconcile-expired-lease")
    expired.add_argument("--ticket", required=True)
    expired.add_argument("--request-id", required=True)
    expired.add_argument("--now", required=True)

    archive = sub.add_parser("record-archive-receipt")
    archive.add_argument("--ticket", required=True)
    archive.add_argument("--request-id", required=True)
    archive.add_argument("--now", required=True)

    legacy_archive = sub.add_parser("reconcile-legacy-archive")
    legacy_archive.add_argument("--request", required=True)

    stale_present_archive = sub.add_parser("reconcile-stale-present-archive")
    stale_present_archive.add_argument("--request", required=True)

    status = sub.add_parser("status")
    status.add_argument("--now")
    return parser


def execute(args: argparse.Namespace) -> dict[str, Any]:
    cli, version = validate_installation(args.cli)
    state_dir = validate_private_dir(args.state_dir, "state directory")
    operation = args.operation

    if operation == "init":
        parse_time(args.now)
        result = run_cli(cli, state_dir, "init", now=args.now)
        return success("init", {"cli_version": version, **result})

    health = doctor(cli, state_dir, version)
    if operation == "doctor":
        return success("doctor", health)
    if operation == "status":
        if args.now is not None:
            parse_time(args.now)
        return success(
            "status", run_cli(cli, state_dir, "status", now=args.now)
        )

    if operation == "root-action":
        if not schema_at_least(health["schema_version"], (1, 2)):
            raise BridgeError(
                "ROOT_GUARD_UNAVAILABLE",
                "root-role enforcement requires Firestarter schema 1.2",
            )
        request = load_json_file(args.request, "root-action request")
        validate_request(request, durable=True)
        return success(operation, run_root_guard(cli, state_dir, request))

    if operation == "reconcile-legacy-archive":
        if not schema_at_least(health["schema_version"], (1, 4)):
            raise BridgeError(
                "LEGACY_ARCHIVE_RECONCILIATION_UNAVAILABLE",
                "legacy archive reconciliation requires Firestarter schema 1.4",
                exit_status=2,
            )
        request = load_json_file(args.request, "legacy archive reconciliation request")
        required = {
            "interface_version",
            "request_id",
            "task_id",
            "expected_source_event_key",
            "external_thread_id",
            "expected_state_revision",
            "policy_snapshot_revision",
            "lease_epoch",
            "fencing_token",
            "owner_claim_id",
            "expected_archive_outbox_id",
            "external_archive_proof",
            "now",
        }
        if set(request) != required:
            raise BridgeError(
                "SCHEMA_INVALID",
                "legacy archive reconciliation request fields are invalid",
                exit_status=2,
            )
        validate_request(request, durable=True)
        parse_time(request.get("now"))
        task_id = request.get("task_id")
        external_thread_id = request.get("external_thread_id")
        if not isinstance(task_id, str) or not isinstance(external_thread_id, str):
            raise BridgeError(
                "LEGACY_ARCHIVE_IDENTITY_INVALID",
                "legacy archive reconciliation requires exact task identities",
                exit_status=2,
            )
        request["missing_transport_ticket_proof"] = (
            require_missing_legacy_transport_ticket(
                state_dir,
                task_id,
                external_thread_id,
                now=request.get("now"),
            )
        )
        result = run_cli(
            cli,
            state_dir,
            "reconcile-legacy-archive",
            request=request,
        )
        expected_fields = {
            "request_id",
            "task_id",
            "external_thread_id",
            "state",
            "archive_outbox_id",
            "external_archive_state",
            "transport_ticket_state",
            "previous_state_revision",
            "committed_state_revision",
            "current_state_revision",
            "replayed",
        }
        if (
            set(result) != expected_fields
            or result.get("request_id") != request["request_id"]
            or result.get("task_id") != task_id
            or result.get("external_thread_id") != external_thread_id
            or result.get("state") != "ARCHIVED"
            or result.get("archive_outbox_id")
            != request["expected_archive_outbox_id"]
            or result.get("external_archive_state")
            != request["external_archive_proof"].get("state")
            or result.get("transport_ticket_state") != "missing"
            or result.get("previous_state_revision")
            != request["expected_state_revision"]
            or not isinstance(result.get("committed_state_revision"), int)
            or result["committed_state_revision"]
            != result["previous_state_revision"] + 1
            or not isinstance(result.get("current_state_revision"), int)
            or result["current_state_revision"]
            < result["committed_state_revision"]
            or not isinstance(result.get("replayed"), bool)
        ):
            raise BridgeError(
                "MACHINE_RESPONSE_INVALID",
                "legacy archive reconciliation result is incompatible",
            )
        return success(operation, result)

    if operation == "reconcile-stale-present-archive":
        if not schema_at_least(health["schema_version"], (1, 4)):
            raise BridgeError(
                "STALE_PRESENT_ARCHIVE_RECONCILIATION_UNAVAILABLE",
                "stale-present archive reconciliation requires Firestarter schema 1.4",
                exit_status=2,
            )
        request = load_json_file(
            args.request, "stale-present archive reconciliation request"
        )
        required = {
            "interface_version",
            "request_id",
            "task_id",
            "expected_source_event_key",
            "external_thread_id",
            "expected_state_revision",
            "policy_snapshot_revision",
            "lease_epoch",
            "fencing_token",
            "owner_claim_id",
            "expected_archive_outbox_id",
            "external_archive_proof",
            "now",
        }
        if set(request) != required:
            raise BridgeError(
                "SCHEMA_INVALID",
                "stale-present archive reconciliation request fields are invalid",
                exit_status=2,
            )
        validate_request(request, durable=True)
        parse_time(request.get("now"))
        task_id = request.get("task_id")
        external_thread_id = request.get("external_thread_id")
        if not isinstance(task_id, str) or not isinstance(external_thread_id, str):
            raise BridgeError(
                "LEGACY_ARCHIVE_IDENTITY_INVALID",
                "stale-present reconciliation requires exact task identities",
                exit_status=2,
            )
        ticket_proof = classify_stale_present_transport_ticket(
            state_dir,
            task_id,
            external_thread_id,
            now=request.get("now"),
        )
        request["transport_ticket_proof"] = ticket_proof
        result = run_cli(
            cli,
            state_dir,
            "reconcile-stale-present-archive",
            request=request,
        )
        expected_fields = {
            "request_id",
            "task_id",
            "external_thread_id",
            "state",
            "archive_outbox_id",
            "owner_claim_state",
            "external_archive_state",
            "transport_ticket_state",
            "transport_ticket_filename",
            "transport_ticket_sha256",
            "transport_ticket_cleanup_state",
            "reconciliation_class",
            "previous_state_revision",
            "committed_state_revision",
            "current_state_revision",
            "replayed",
        }
        if (
            set(result) != expected_fields
            or result.get("request_id") != request["request_id"]
            or result.get("task_id") != task_id
            or result.get("external_thread_id") != external_thread_id
            or result.get("state") != "ARCHIVED"
            or result.get("archive_outbox_id")
            != request["expected_archive_outbox_id"]
            or result.get("owner_claim_state") != "released"
            or result.get("external_archive_state")
            != request["external_archive_proof"].get("state")
            or result.get("transport_ticket_state") != "stale-present"
            or not isinstance(result.get("transport_ticket_filename"), str)
            or not isinstance(result.get("transport_ticket_sha256"), str)
            or result.get("transport_ticket_cleanup_state")
            != "pending-post-commit"
            or result.get("reconciliation_class")
            not in {
                "RECEIPT_STALE_TERMINAL",
                "CAPACITY_EMPTY_TERMINAL",
                "CAPACITY_ARCHIVED_SUCCESSOR_TERMINAL",
            }
            or result.get("previous_state_revision")
            != request["expected_state_revision"]
            or not isinstance(result.get("committed_state_revision"), int)
            or result["committed_state_revision"]
            != result["previous_state_revision"] + 1
            or not isinstance(result.get("current_state_revision"), int)
            or result["current_state_revision"]
            < result["committed_state_revision"]
            or not isinstance(result.get("replayed"), bool)
            or (
                ticket_proof["state"] == "stale-present"
                and (
                    result["transport_ticket_filename"]
                    != ticket_proof["ticket_filename"]
                    or result["transport_ticket_sha256"]
                    != ticket_proof["ticket_sha256"]
                )
            )
        ):
            raise BridgeError(
                "MACHINE_RESPONSE_INVALID",
                "stale-present archive reconciliation result is incompatible",
            )
        remove_committed_stale_ticket(state_dir, ticket_proof, result)
        result["transport_ticket_cleanup_state"] = "completed"
        return success(operation, result)

    if operation == "route-owner-decision":
        request = load_json_file(args.request, "route-owner-decision request")
        validate_owner_decision_route_request(request)
        _path, ticket = load_ticket(args.ticket)
        require_active_receipt(ticket, request["now"])
        require_external_identity(ticket, args.external_thread_id)
        if request["source_thread_id"] != ticket["receipt"]["external_thread_id"]:
            raise BridgeError(
                "RECEIPT_MISMATCH",
                "decision route source is not the receipt-backed worker",
                exit_status=2,
            )
        classified = run_cli(
            cli,
            state_dir,
            "classify-decision",
            request=request["decision_request"],
        )
        route = classified.get("classification")
        owner_prompt_required = classified.get("owner_prompt_required")
        if route == "PM_PROXY" and owner_prompt_required is False:
            return success(
                operation,
                {
                    "classification": "PM_PROXY",
                    "auto_return": True,
                    "route_required": False,
                    "source_thread_id": request["source_thread_id"],
                    "request_id": request["approval"]["request_id"],
                    "reason_code": classified["reason_code"],
                    "owner_prompt_required": False,
                    "notification_deduplicated": classified[
                        "notification_deduplicated"
                    ],
                    "sink_thread_id": None,
                    "decision_envelope": None,
                },
            )
        if route != "OWNER_GATE" or owner_prompt_required is not True:
            raise BridgeError(
                "OWNER_GATE_DOWNGRADE",
                "only a verified typed owner gate may reach the owner sink",
                exit_status=2,
            )
        envelope = {
            "envelope_version": "1.0",
            "kind": "OWNER_DECISION_REQUEST",
            "route_request_id": request["route_request_id"],
            "source_thread_id": request["source_thread_id"],
            "sink_thread_id": OWNER_DECISION_SINK_THREAD_ID,
            "request_id": request["approval"]["request_id"],
            "decision_code": request["approval"]["decision_code"],
            "option_codes": request["approval"]["option_codes"],
            "evidence_refs": request["approval"]["evidence_refs"],
            "action_type": request["decision_request"]["action_type"],
            "gate_type": request["decision_request"]["gate_type"],
            "classification": "OWNER_GATE",
            "reason_code": classified["reason_code"],
            "rule_ids": classified["rule_ids"],
            "verified_owner_gate": True,
            "capacity_reserved": False,
            "sink_authority": False,
            "recursion_depth": 0,
        }
        return success(
            operation,
            {
                "classification": "OWNER_GATE",
                "auto_return": False,
                "route_required": True,
                "source_thread_id": request["source_thread_id"],
                "request_id": request["approval"]["request_id"],
                "reason_code": classified["reason_code"],
                "owner_prompt_required": True,
                "notification_deduplicated": classified[
                    "notification_deduplicated"
                ],
                "sink_thread_id": OWNER_DECISION_SINK_THREAD_ID,
                "decision_envelope": envelope,
            },
        )

    if operation in {
        "record-policy-rule",
        "effective-rules",
        "classify-decision",
        "recycle-queue",
        "duration-estimate",
        "duration-schedule",
        "record-dispatcher-adoption",
        "configure-capacity",
    }:
        request = load_json_file(args.request, f"{operation} request")
        if operation == "record-policy-rule":
            validate_policy_request(request)
        else:
            validate_request(request, durable=True)
        if operation.startswith("duration-") and not schema_at_least(
            health["schema_version"], (1, 2)
        ):
            raise BridgeError(
                "FEATURE_UNSUPPORTED",
                "duration control requires Firestarter schema 1.2",
                exit_status=2,
            )
        if operation == "configure-capacity" and not schema_at_least(
            health["schema_version"], (1, 3)
        ):
            raise BridgeError(
                "FEATURE_UNSUPPORTED",
                "capacity reconfiguration requires Firestarter schema 1.3",
                exit_status=2,
            )
        result = run_cli(cli, state_dir, operation, request=request)
        if operation == "configure-capacity":
            validate_capacity_result(result, request)
        if operation == "classify-decision":
            route = result.get("classification")
            prompt_required = result.get("owner_prompt_required")
            deduplicated = result.get("notification_deduplicated")
            if route not in {"PM_PROXY", "OWNER_GATE"}:
                raise BridgeError("DECISION_DENIED", "unknown decision route", exit_status=2)
            if route == "PM_PROXY" and prompt_required is not False:
                raise BridgeError("OWNER_GATE_DOWNGRADE", "owner prompt flag contradicts route", exit_status=2)
            if route == "OWNER_GATE" and prompt_required is not True and deduplicated is not True:
                raise BridgeError("OWNER_GATE_DOWNGRADE", "owner gate was silently downgraded", exit_status=2)
        return success(operation, result)

    if operation == "prepare-launch":
        recycle = load_json_file(args.recycle_request, "recycle request")
        launch = load_json_file(args.launch_request, "launch request")
        validate_request(recycle, durable=True)
        validate_request(launch, durable=False)
        run_cli(cli, state_dir, "recycle-queue", request=recycle)
        result = run_cli(cli, state_dir, "prepare-launch", request=launch)
        envelope, rule_ids = validate_prepare_result(result)
        issued = parse_time(envelope["issued_at"])
        request_now = parse_time(launch["now"])
        if issued != request_now:
            raise BridgeError("RECEIPT_INVALID", "envelope issued_at must equal launch now", exit_status=2)
        ticket_path = require_absolute(args.ticket, "ticket", must_exist=False)
        ticket = {
            "ticket_version": TICKET_VERSION,
            "control_schema_version": health["schema_version"],
            "task_id": envelope["task_id"],
            "source_event_key": envelope["source_event_key"],
            "outcome_key": envelope["outcome_key"],
            "issued_at": envelope["issued_at"],
            "receipt_deadline": format_time(issued + dt.timedelta(seconds=LAUNCH_RECEIPT_TTL_SECONDS)),
            "lease_expires_at": launch["lease_expires_at"],
            "policy_snapshot_revision": envelope["policy_snapshot_revision"],
            "lease_epoch": envelope["lease_epoch"],
            "fencing_token": envelope["fencing_token"],
            "applicable_rule_ids": rule_ids,
            "runtime_policy": envelope["receipt_required"]["runtime_policy"],
            "outbox": result["outbox"],
            "receipt": None,
            "last_heartbeat_at": None,
            "handback": None,
            "duration_estimate": envelope.get("duration_estimate"),
            "owner_claim_id": envelope.get("owner_claim_id"),
        }
        write_ticket_new(ticket_path, ticket)
        return success(
            "prepare-launch",
            {
                "prompt": result["prompt"],
                "outbox": result["outbox"],
                "ticket": str(ticket_path),
                "task_id": ticket["task_id"],
                "policy_snapshot_revision": ticket["policy_snapshot_revision"],
                "applicable_rule_ids": rule_ids,
                "runtime_policy": ticket["runtime_policy"],
                "lease_epoch": ticket["lease_epoch"],
                "fencing_token": ticket["fencing_token"],
                "receipt_deadline": ticket["receipt_deadline"],
            },
        )

    if operation == "record-launch-receipt":
        parse_time(args.now)
        path, ticket = load_ticket(args.ticket)
        require_fresh_unreceipted(ticket, args.now)
        runtime_attestation = validate_runtime_attestation(
            load_json_file(args.runtime_attestation, "runtime attestation")
        )
        request = {
            "interface_version": INTERFACE_VERSION,
            "request_id": args.request_id,
            "task_id": ticket["task_id"],
            "policy_snapshot_revision": ticket["policy_snapshot_revision"],
            "lease_epoch": ticket["lease_epoch"],
            "fencing_token": ticket["fencing_token"],
            "external_thread_id": args.external_thread_id,
            "applicable_rule_ids": ticket["applicable_rule_ids"],
            "runtime_attestation": runtime_attestation,
            "now": args.now,
        }
        validate_request(request, durable=True)
        result = run_cli(cli, state_dir, "record-launch-receipt", request=request)
        ticket["receipt"] = {
            "external_thread_id": args.external_thread_id,
            "recorded_at": args.now,
            "runtime_attestation": runtime_attestation,
        }
        replace_ticket(path, ticket)
        return success("record-launch-receipt", result)

    if operation == "reconcile-external-task":
        parse_time(args.now)
        _, ticket = load_ticket(args.ticket)
        receipt = ticket.get("receipt")
        if not isinstance(receipt, dict) or not isinstance(
            receipt.get("external_thread_id"), str
        ):
            raise BridgeError(
                "EXTERNAL_RECEIPT_REQUIRED",
                "external reconciliation requires the canonical receipt",
                exit_status=2,
            )
        request = {
            "interface_version": INTERFACE_VERSION,
            "request_id": args.request_id,
            "task_id": ticket["task_id"],
            "source_event_key": ticket["source_event_key"],
            "outcome_key": ticket["outcome_key"],
            "external_thread_id": args.external_thread_id,
            "now": args.now,
        }
        if schema_at_least(health["schema_version"], (1, 1)):
            result = run_cli(
                cli, state_dir, "reconcile-external-task", request=request
            )
        else:
            canonical_external_id = receipt["external_thread_id"]
            canonical = args.external_thread_id == canonical_external_id
            result = {
                "classification": (
                    "CANONICAL_RECEIPT_CONFIRMED"
                    if canonical
                    else "DUPLICATE_STOP"
                ),
                "canonical_external_thread_id": canonical_external_id,
                "mutation_allowed": canonical,
                "capacity_eligible": canonical,
                "required_actions": (
                    []
                    if canonical
                    else [
                        "STOP_READ_ONLY",
                        "RETURN_ZERO_CHANGE_HANDBACK",
                        "ARCHIVE_EXTERNAL_MIRROR",
                    ]
                ),
                "zero_change_handback": (
                    None
                    if canonical
                    else {
                        "disposition": "duplicate",
                        "changes": 0,
                        "evidence_refs": [
                            f"external-mirror:{args.request_id}"
                        ],
                    }
                ),
            }
        if result.get("classification") == "DUPLICATE_STOP":
            if result.get("mutation_allowed") is not False or result.get(
                "capacity_eligible"
            ) is not False:
                raise BridgeError(
                    "MACHINE_RESPONSE_INVALID",
                    "external mirror was not excluded from mutation and capacity",
                )
        return success(operation, result)

    if operation == "heartbeat":
        parse_time(args.now)
        parse_time(args.lease_expires_at)
        if parse_time(args.lease_expires_at) <= parse_time(args.now):
            raise BridgeError("LEASE_INVALID", "lease_expires_at must be after now", exit_status=2)
        path, ticket = load_ticket(args.ticket)
        require_active_receipt(ticket, args.now)
        require_external_identity(ticket, args.external_thread_id)
        request = {
            "interface_version": INTERFACE_VERSION,
            "request_id": args.request_id,
            "task_id": ticket["task_id"],
            "policy_snapshot_revision": ticket["policy_snapshot_revision"],
            "lease_epoch": ticket["lease_epoch"],
            "fencing_token": ticket["fencing_token"],
            "lease_expires_at": args.lease_expires_at,
            "now": args.now,
        }
        if schema_at_least(health["schema_version"], (1, 1)):
            request["external_thread_id"] = ticket["receipt"][
                "external_thread_id"
            ]
        result = run_cli(cli, state_dir, "record-heartbeat", request=request)
        ticket["lease_expires_at"] = args.lease_expires_at
        ticket["last_heartbeat_at"] = args.now
        replace_ticket(path, ticket)
        return success("heartbeat", result)

    if operation == "lifecycle-watchdog":
        if not schema_at_least(health["schema_version"], (1, 3)):
            raise BridgeError(
                "FEATURE_UNSUPPORTED",
                "lifecycle watchdog requires Firestarter schema 1.3",
                exit_status=2,
            )
        request = load_json_file(args.request, "lifecycle-watchdog request")
        validate_request(request, durable=False)
        path, ticket = load_ticket(args.ticket)
        require_active_receipt(ticket, request.get("now"))
        require_external_identity(ticket, args.external_thread_id)
        inject_ticket_fields(request, ticket)
        request["external_thread_id"] = ticket["receipt"]["external_thread_id"]
        result = run_cli(
            cli,
            state_dir,
            "lifecycle-watchdog",
            request=request,
        )
        lifecycle = result.get("lifecycle")
        if not isinstance(lifecycle, dict):
            raise BridgeError(
                "MACHINE_RESPONSE_INVALID",
                "lifecycle watchdog omitted lifecycle state",
            )
        successor = result.get("successor")
        successor_launch = None
        if lifecycle.get("lifecycle_state") == "INTERRUPTED":
            ticket["handback"] = {
                "recorded_at": request["now"],
                "state": "INTERRUPTED",
                "source": "lifecycle-watchdog",
            }
            if successor is not None:
                if not args.successor_ticket:
                    raise BridgeError(
                        "SUCCESSOR_TICKET_REQUIRED",
                        "interrupt refill returned a successor without a ticket path",
                        exit_status=2,
                    )
                successor_request = request.get("capacity", {}).get(
                    "successor_request"
                )
                if not isinstance(successor_request, dict):
                    raise BridgeError(
                        "MACHINE_RESPONSE_INVALID",
                        "successor result has no matching request",
                    )
                envelope, rule_ids = validate_prepare_result(successor)
                if successor_request.get("task_id") != envelope["task_id"]:
                    raise BridgeError(
                        "MACHINE_RESPONSE_INVALID",
                        "successor task does not match the interrupt request",
                    )
                issued = parse_time(envelope["issued_at"])
                successor_path = require_absolute(
                    args.successor_ticket,
                    "successor ticket",
                    must_exist=False,
                )
                successor_ticket = {
                    "ticket_version": TICKET_VERSION,
                    "control_schema_version": health["schema_version"],
                    "task_id": envelope["task_id"],
                    "source_event_key": envelope["source_event_key"],
                    "outcome_key": envelope["outcome_key"],
                    "issued_at": envelope["issued_at"],
                    "receipt_deadline": format_time(
                        issued
                        + dt.timedelta(seconds=LAUNCH_RECEIPT_TTL_SECONDS)
                    ),
                    "lease_expires_at": successor_request["lease_expires_at"],
                    "policy_snapshot_revision": envelope[
                        "policy_snapshot_revision"
                    ],
                    "lease_epoch": envelope["lease_epoch"],
                    "fencing_token": envelope["fencing_token"],
                    "applicable_rule_ids": rule_ids,
                    "outbox": successor["outbox"],
                    "receipt": None,
                    "last_heartbeat_at": None,
                    "handback": None,
                    "duration_estimate": envelope.get("duration_estimate"),
                    "owner_claim_id": envelope.get("owner_claim_id"),
                    "runtime_policy": envelope["receipt_required"][
                        "runtime_policy"
                    ],
                }
                write_ticket_new(successor_path, successor_ticket)
                successor_launch = {
                    "task_id": envelope["task_id"],
                    "prompt": successor.get("prompt"),
                    "outbox": successor["outbox"],
                    "ticket": str(successor_path),
                    "fencing_token": envelope["fencing_token"],
                }
            elif args.successor_ticket:
                raise BridgeError(
                    "SUCCESSOR_TICKET_CONFLICT",
                    "interrupt without a successor cannot create a ticket",
                    exit_status=2,
                )
            replace_ticket(path, ticket)
        elif args.successor_ticket:
            raise BridgeError(
                "SUCCESSOR_TICKET_CONFLICT",
                "observe requests cannot create successor tickets",
                exit_status=2,
            )
        return success(
            "lifecycle-watchdog",
            {
                **result,
                "successor_launch": successor_launch,
            },
        )

    if operation == "acknowledge-control-schema-hold":
        if not schema_at_least(health["schema_version"], (1, 4)):
            raise BridgeError(
                "FEATURE_UNSUPPORTED",
                "control-schema hold acknowledgement requires Firestarter schema 1.4",
                exit_status=2,
            )
        request = load_json_file(
            args.request, "acknowledge-control-schema-hold request"
        )
        validate_request(request, durable=True)
        _path, ticket = load_ticket(args.ticket)
        receipt = require_committed_receipt(ticket)
        require_external_identity(ticket, args.external_thread_id)
        inject_ticket_fields(request, ticket)
        request["external_thread_id"] = receipt["external_thread_id"]
        if request.get("ticket_id") != ticket["source_event_key"]:
            raise BridgeError(
                "RECEIPT_MISMATCH",
                "control-schema hold ticket identity changed",
                exit_status=2,
            )
        result = run_cli(
            cli,
            state_dir,
            "acknowledge-control-schema-hold",
            request=request,
        )
        preservation = result.get("preservation")
        exact = {
            "ticket_id": ticket["source_event_key"],
            "task_id": ticket["task_id"],
            "external_thread_id": receipt["external_thread_id"],
            "policy_snapshot_revision": ticket["policy_snapshot_revision"],
            "lease_epoch": ticket["lease_epoch"],
            "fencing_token": ticket["fencing_token"],
            "hold_state": "CONTROL_SCHEMA_HOLD",
            "required_action": "AWAIT_CONTROL_REPAIR",
            "replay_target": "completed_local_only",
        }
        if any(result.get(key) != value for key, value in exact.items()):
            raise BridgeError(
                "MACHINE_RESPONSE_INVALID",
                "control-schema hold result changed its exact binding",
            )
        if (
            not isinstance(preservation, dict)
            or preservation.get("task_state") != "RUNNING"
            or preservation.get("claim_status") != "active"
            or preservation.get("occupied_lane") is not True
            or preservation.get("external_worker_state") != "PRESERVED"
            or preservation.get("capacity_released") is not False
            or preservation.get("handback_created") is not False
            or preservation.get("archive_created") is not False
            or preservation.get("refill_created") is not False
        ):
            raise BridgeError(
                "MACHINE_RESPONSE_INVALID",
                "control-schema hold did not preserve the occupied fenced task",
            )
        return success(operation, result)

    if operation == "record-handback":
        request = load_json_file(args.request, "record-handback request")
        validate_handback_request(request)
        path, ticket = load_ticket(args.ticket)
        require_active_receipt(ticket, request.get("now"))
        require_external_identity(ticket, args.external_thread_id)
        if request.get("disposition") != "blocked":
            raise BridgeError(
                "CLOSURE_SAGA_REQUIRED",
                "terminal handback must use refill_saga.py close-and-refill",
                exit_status=2,
            )
        inject_ticket_fields(request, ticket)
        if schema_at_least(health["schema_version"], (1, 1)):
            request["external_thread_id"] = ticket["receipt"][
                "external_thread_id"
            ]
        result = run_cli(cli, state_dir, "record-handback", request=request)
        if ticket.get("handback") is None:
            ticket["handback"] = {
                "recorded_at": request["now"],
                "state": result.get("state"),
            }
            replace_ticket(path, ticket)
        return success("record-handback", result)

    if operation in {"record-duration-progress", "record-duration-observation"}:
        if not schema_at_least(health["schema_version"], (1, 2)):
            raise BridgeError(
                "FEATURE_UNSUPPORTED",
                "duration control requires Firestarter schema 1.2",
                exit_status=2,
            )
        request = load_json_file(args.request, f"{operation} request")
        validate_request(request, durable=True)
        path, ticket = load_ticket(args.ticket)
        require_active_receipt(ticket, request.get("now"))
        require_external_identity(ticket, args.external_thread_id)
        inject_ticket_fields(request, ticket)
        request["external_thread_id"] = ticket["receipt"]["external_thread_id"]
        result = run_cli(cli, state_dir, operation, request=request)
        if operation == "record-duration-progress" and result.get("reclassified"):
            duration = result.get("duration")
            if not isinstance(duration, dict):
                raise BridgeError(
                    "MACHINE_RESPONSE_INVALID",
                    "duration reclassification omitted durable estimate",
                )
            ticket["duration_estimate"] = duration
            replace_ticket(path, ticket)
        return success(operation, result)

    if operation == "record-setup-failure":
        if not schema_at_least(health["schema_version"], (1, 2)):
            raise BridgeError(
                "FEATURE_UNSUPPORTED",
                "setup-failure recovery requires Firestarter schema 1.2",
                exit_status=2,
            )
        request = load_json_file(args.request, "record-setup-failure request")
        validate_setup_failure_request(request)
        path, ticket = load_ticket(args.ticket)
        require_unreceipted_setup_ticket(ticket, request.get("now"))
        inject_ticket_fields(request, ticket)
        outbox = ticket.get("outbox")
        if not isinstance(outbox, dict) or not isinstance(
            outbox.get("outbox_id"), str
        ):
            raise BridgeError(
                "RECEIPT_INVALID",
                "setup failure requires its exact create outbox",
                exit_status=2,
            )
        request["expected_outbox_id"] = outbox["outbox_id"]
        if not isinstance(ticket.get("owner_claim_id"), str):
            raise BridgeError(
                "RECEIPT_INVALID",
                "setup failure requires its exact owner claim",
                exit_status=2,
            )
        request["expected_owner_claim_id"] = ticket["owner_claim_id"]
        result = run_cli(cli, state_dir, operation, request=request)
        if (
            result.get("failed_outbox_id") != outbox["outbox_id"]
            or result.get("released_owner_claim_id")
            != ticket["owner_claim_id"]
            or result.get("released_claim_count") != 1
            or result.get("poisoned_outbox_count") != 1
        ):
            raise BridgeError(
                "MACHINE_RESPONSE_INVALID",
                "setup failure changed its exact outbox or claim binding",
            )
        ticket["handback"] = {
            "recorded_at": request["now"],
            "state": result.get("state"),
        }
        replace_ticket(path, ticket)
        successor = result.get("successor")
        successor_launch = None
        if successor is not None:
            if args.successor_ticket is None:
                raise BridgeError(
                    "SUCCESSOR_TICKET_REQUIRED",
                    "selected setup-failure successor requires an exact ticket path",
                    exit_status=2,
                )
            envelope, rule_ids = validate_prepare_result(successor)
            selected = next(
                (
                    candidate
                    for candidate in request["successor_candidates"]
                    if candidate.get("task_id") == envelope["task_id"]
                ),
                None,
            )
            if selected is None:
                raise BridgeError(
                    "MACHINE_RESPONSE_INVALID",
                    "setup-failure successor was not an offered candidate",
                )
            issued = parse_time(envelope["issued_at"])
            successor_path = require_absolute(
                args.successor_ticket,
                "successor ticket",
                must_exist=False,
            )
            successor_ticket = {
                "ticket_version": TICKET_VERSION,
                "control_schema_version": health["schema_version"],
                "task_id": envelope["task_id"],
                "source_event_key": envelope["source_event_key"],
                "outcome_key": envelope["outcome_key"],
                "issued_at": envelope["issued_at"],
                "receipt_deadline": format_time(
                    issued + dt.timedelta(seconds=LAUNCH_RECEIPT_TTL_SECONDS)
                ),
                "lease_expires_at": selected["lease_expires_at"],
                "policy_snapshot_revision": envelope["policy_snapshot_revision"],
                "lease_epoch": envelope["lease_epoch"],
                "fencing_token": envelope["fencing_token"],
                "applicable_rule_ids": rule_ids,
                "outbox": successor["outbox"],
                "receipt": None,
                "last_heartbeat_at": None,
                "handback": None,
                "duration_estimate": envelope.get("duration_estimate"),
                "owner_claim_id": envelope.get("owner_claim_id"),
                "runtime_policy": envelope["receipt_required"][
                    "runtime_policy"
                ],
            }
            write_ticket_new(successor_path, successor_ticket)
            successor_launch = {
                "task_id": envelope["task_id"],
                "prompt": successor["prompt"],
                "outbox": successor["outbox"],
                "ticket": str(successor_path),
                "fencing_token": envelope["fencing_token"],
            }
        elif args.successor_ticket is not None:
            successor_path = require_absolute(
                args.successor_ticket,
                "successor ticket",
                must_exist=False,
            )
            if successor_path.exists():
                raise BridgeError(
                    "SUCCESSOR_TICKET_CONFLICT",
                    "empty setup recovery cannot create a successor ticket",
                    exit_status=2,
                )
        return success(
            operation,
            {
                **result,
                "successor_launch": successor_launch,
            },
        )

    if operation == "takeover-lease":
        request = load_json_file(args.request, "takeover-lease request")
        validate_request(request, durable=True)
        path, ticket = load_ticket(args.ticket)
        if request.get("task_id") != ticket["task_id"]:
            raise BridgeError("RECEIPT_MISMATCH", "takeover task does not match ticket", exit_status=2)
        if request.get("expected_lease_epoch") != ticket["lease_epoch"]:
            raise BridgeError("RECEIPT_MISMATCH", "takeover lease epoch does not match ticket", exit_status=2)
        if request.get("expected_fencing_token") != ticket["fencing_token"]:
            raise BridgeError("RECEIPT_MISMATCH", "takeover fence does not match ticket", exit_status=2)
        result = run_cli(cli, state_dir, "takeover-lease", request=request)
        if result.get("task_id") != ticket["task_id"]:
            raise BridgeError("MACHINE_RESPONSE_INVALID", "takeover result task mismatch")
        if not isinstance(result.get("lease_epoch"), int) or not isinstance(result.get("fencing_token"), int):
            raise BridgeError("MACHINE_RESPONSE_INVALID", "takeover result fence is incomplete")
        if result["lease_epoch"] <= ticket["lease_epoch"] or result["fencing_token"] <= ticket["fencing_token"]:
            raise BridgeError("MACHINE_RESPONSE_INVALID", "takeover did not advance fencing")
        ticket["lease_epoch"] = result["lease_epoch"]
        ticket["fencing_token"] = result["fencing_token"]
        ticket["lease_expires_at"] = request["lease_expires_at"]
        ticket["last_heartbeat_at"] = request["now"]
        replace_ticket(path, ticket)
        return success("takeover-lease", result)

    if operation == "reconcile-expired-lease":
        parse_time(args.now)
        _, ticket = load_ticket(args.ticket)
        receipt = require_committed_receipt(ticket)
        if parse_time(args.now) < parse_time(ticket["lease_expires_at"]):
            raise BridgeError(
                "LEASE_NOT_EXPIRED",
                "worker lease is still live",
                exit_status=3,
            )
        if not isinstance(ticket.get("owner_claim_id"), str):
            raise BridgeError(
                "RECEIPT_INVALID",
                "expired-lease reconciliation requires an exact owner claim",
                exit_status=2,
            )
        request = {
            "interface_version": INTERFACE_VERSION,
            "request_id": args.request_id,
            "task_id": ticket["task_id"],
            "policy_snapshot_revision": ticket["policy_snapshot_revision"],
            "expected_lease_epoch": ticket["lease_epoch"],
            "expected_fencing_token": ticket["fencing_token"],
            "expected_owner_claim_id": ticket["owner_claim_id"],
            "expected_external_thread_id": receipt["external_thread_id"],
            "expected_lease_expires_at": ticket["lease_expires_at"],
            "now": args.now,
        }
        result = run_cli(
            cli,
            state_dir,
            "reconcile-expired-lease",
            request=request,
        )
        exact = {
            "task_id": ticket["task_id"],
            "external_thread_id": receipt["external_thread_id"],
            "state": "EXPIRED",
            "claim_id": ticket["owner_claim_id"],
            "claim_status": "expired",
            "lease_expires_at": ticket["lease_expires_at"],
            "retired_lease_epoch": ticket["lease_epoch"],
            "retired_fencing_token": ticket["fencing_token"],
            "capacity_released": True,
            "closure_created": False,
            "archive_created": False,
            "refill_created": False,
            "required_action": "NONE",
        }
        if any(result.get(key) != value for key, value in exact.items()):
            raise BridgeError(
                "MACHINE_RESPONSE_INVALID",
                "expired-lease result does not match the exact ticket tombstone",
            )
        if (
            set(result) != set(exact) | {"tombstone_fencing_token", "replayed"}
            or not isinstance(result["tombstone_fencing_token"], int)
            or result["tombstone_fencing_token"] <= ticket["fencing_token"]
            or not isinstance(result["replayed"], bool)
        ):
            raise BridgeError(
                "MACHINE_RESPONSE_INVALID",
                "expired-lease result fence or fields are incompatible",
            )
        return success("reconcile-expired-lease", result)

    if operation == "record-archive-receipt":
        parse_time(args.now)
        path, ticket = load_ticket(args.ticket)
        require_committed_receipt(ticket)
        expired = parse_time(args.now) >= parse_time(ticket["lease_expires_at"])
        handback = ticket.get("handback")
        if not isinstance(handback, dict):
            if expired:
                raise BridgeError(
                    "RECEIPT_STALE",
                    "expired receipt has no exact terminal archive admission",
                    exit_status=2,
                )
            raise BridgeError(
                "HANDBACK_MISSING",
                "handback is required before archive receipt",
                exit_status=2,
            )
        status = None
        saga = None
        if expired:
            status = run_cli(cli, state_dir, "status", now=args.now)
            saga = require_refill_saga_before_archive(
                state_dir,
                ticket["task_id"],
                status=status,
            )
            require_terminal_archive_admission(
                status,
                ticket,
                saga,
                expired=True,
            )
        elif handback.get("source") != "lifecycle-watchdog":
            try:
                saga = require_refill_saga_before_archive(
                    state_dir, ticket["task_id"]
                )
            except BridgeError as error:
                if error.code != "CAPACITY_REFILL_PENDING":
                    raise
                status = run_cli(cli, state_dir, "status", now=args.now)
                saga = require_refill_saga_before_archive(
                    state_dir,
                    ticket["task_id"],
                    status=status,
                )
                require_terminal_archive_admission(
                    status,
                    ticket,
                    saga,
                    expired=False,
                )
        request = {
            "interface_version": INTERFACE_VERSION,
            "request_id": args.request_id,
            "task_id": ticket["task_id"],
            "policy_snapshot_revision": ticket["policy_snapshot_revision"],
            "lease_epoch": ticket["lease_epoch"],
            "fencing_token": ticket["fencing_token"],
            "now": args.now,
        }
        result = run_cli(cli, state_dir, "record-archive-receipt", request=request)
        if handback.get("archive_receipt_at") is None:
            handback["archive_receipt_at"] = args.now
            replace_ticket(path, ticket)
        return success("record-archive-receipt", result)

    raise BridgeError("COMMAND_DENIED", "unsupported bridge operation", exit_status=2)


def main() -> int:
    parser = build_parser()
    try:
        response = execute(parser.parse_args())
    except BridgeError as error:
        emit(fail_payload(error), stream=sys.stderr)
        return error.exit_status
    except Exception:
        error = BridgeError("BRIDGE_FAILURE", "unexpected local bridge failure")
        emit(fail_payload(error), stream=sys.stderr)
        return error.exit_status
    emit(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
