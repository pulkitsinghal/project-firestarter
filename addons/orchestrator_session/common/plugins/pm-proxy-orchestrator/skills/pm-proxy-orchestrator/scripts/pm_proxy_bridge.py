#!/usr/bin/env python3
"""Fail-closed bridge for Firestarter orchestrator-control interface 1.0."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


BRIDGE_VERSION = "1.3"
INTERFACE_VERSION = "1.0"
TICKET_VERSION = "1.3"
LEGACY_TICKET_VERSIONS = {"1.0", "1.2"}
SUPPORTED_SCHEMA_VERSIONS = {"1.0", "1.1", "1.2", "1.3"}
LAUNCH_RECEIPT_TTL_SECONDS = 300
MAX_MACHINE_OUTPUT = 1_048_576
MAX_REQUEST_BYTES = 524_288
CLI_TIMEOUT_SECONDS = 15
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
        "record-handback",
        "record-archive-receipt",
        "capacity-watchdog",
        "lifecycle-watchdog",
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
    if command == "init":
        if now is None:
            raise BridgeError("SCHEMA_INVALID", "init requires --now", exit_status=2)
        argv.extend(["--now", now])
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


def require_active_receipt(ticket: dict[str, Any], now: str) -> None:
    receipt = ticket.get("receipt")
    if not isinstance(receipt, dict) or set(receipt) != {
        "external_thread_id",
        "recorded_at",
        "runtime_attestation",
    }:
        raise BridgeError("RECEIPT_MISSING", "committed exact launch receipt is required", exit_status=2)
    if parse_time(now) > parse_time(ticket["lease_expires_at"]):
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


def require_refill_saga_before_archive(state_dir: Path, task_id: str) -> None:
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
    matching = [
        saga
        for saga in ledger.get("sagas", {}).values()
        if isinstance(saga, dict) and saga.get("predecessor_task_id") == task_id
    ]
    if len(matching) != 1:
        raise BridgeError(
            "CAPACITY_SAGA_MISSING",
            "exact predecessor refill saga is required",
            exit_status=2,
        )
    if matching[0].get("outcome") not in {
        "REFILL_SATISFIED",
        "EMPTY",
        "OWNER_GATED",
        "CAPACITY_FULL",
    }:
        raise BridgeError(
            "CAPACITY_REFILL_PENDING",
            "successor receipt or durable empty/owner-gated/full evidence is required",
            exit_status=2,
            details={"outcome": matching[0].get("outcome")},
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
    setup_failure.add_argument("--successor-ticket", required=True)
    setup_failure.add_argument("--request", required=True)

    takeover = sub.add_parser("takeover-lease")
    takeover.add_argument("--ticket", required=True)
    takeover.add_argument("--request", required=True)

    archive = sub.add_parser("record-archive-receipt")
    archive.add_argument("--ticket", required=True)
    archive.add_argument("--request-id", required=True)
    archive.add_argument("--now", required=True)

    sub.add_parser("status")
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
        return success("status", run_cli(cli, state_dir, "status"))

    if operation == "root-action":
        if not schema_at_least(health["schema_version"], (1, 2)):
            raise BridgeError(
                "ROOT_GUARD_UNAVAILABLE",
                "root-role enforcement requires Firestarter schema 1.2",
            )
        request = load_json_file(args.request, "root-action request")
        validate_request(request, durable=True)
        return success(operation, run_root_guard(cli, state_dir, request))

    if operation in {
        "record-policy-rule",
        "effective-rules",
        "classify-decision",
        "recycle-queue",
        "duration-estimate",
        "duration-schedule",
        "record-dispatcher-adoption",
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
        result = run_cli(cli, state_dir, operation, request=request)
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
        require_fresh_unreceipted(ticket, request.get("now"))
        inject_ticket_fields(request, ticket)
        result = run_cli(cli, state_dir, operation, request=request)
        ticket["handback"] = {
            "recorded_at": request["now"],
            "state": result.get("state"),
        }
        replace_ticket(path, ticket)
        successor = result.get("successor")
        successor_launch = None
        if successor is not None:
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

    if operation == "record-archive-receipt":
        parse_time(args.now)
        path, ticket = load_ticket(args.ticket)
        require_active_receipt(ticket, args.now)
        if not isinstance(ticket.get("handback"), dict):
            raise BridgeError("HANDBACK_MISSING", "handback is required before archive receipt", exit_status=2)
        if ticket["handback"].get("source") != "lifecycle-watchdog":
            require_refill_saga_before_archive(state_dir, ticket["task_id"])
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
        ticket["handback"]["archive_receipt_at"] = args.now
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
