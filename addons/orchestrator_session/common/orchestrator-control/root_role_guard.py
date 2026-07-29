#!/usr/bin/env python3
"""Fail-closed guard for actions proposed by the root orchestrator.

The root orchestrator is a control-plane role, not a task worker.  This module
provides a deliberately small API that an orchestrator can call before every
root action:

    result = evaluate_action(request, state_file=Path("root-role-audit.json"))

Only bounded classification metadata is persisted.  Request descriptions,
prompts, paths, receipt values, and worker evidence values are never written to
the audit file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


INTERFACE_VERSION = "1.0"
MAX_AUDIT_RECORDS = 256
OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

ORCHESTRATION_ACTIONS = frozenset(
    {
        "receive_owner_intent",
        "reserve_visible_task",
        "prepare_visible_task",
        "launch_visible_task",
        "deduplicate_ownership",
        "route_pm_proxy_decision",
        "monitor_receipt",
        "monitor_handback",
        "refill_capacity",
        "synthesize_worker_evidence",
        "notify_owner",
    }
)

TASK_EXECUTION_ACTIONS = frozenset(
    {
        "inspect_repository",
        "inspect_task_domain",
        "design_solution",
        "implement_code",
        "run_tests",
        "estimate_duration",
        "deploy",
        "cleanup",
    }
)

PROHIBITED_REQUEST_KEYS = frozenset(
    {
        "prompt",
        "raw_prompt",
        "private_content",
        "private_prompt",
        "phi",
        "secret",
        "credential",
        "repo_path",
        "path",
        "filesystem_path",
    }
)

STATUS_EVIDENCE = {
    "assigned": frozenset({"launch_receipt"}),
    "running": frozenset({"launch_receipt", "heartbeat"}),
    "validated": frozenset({"worker_handback", "validation"}),
    "merged": frozenset({"worker_handback", "merge"}),
    "deployed": frozenset({"worker_handback", "deployment"}),
}
MAX_EXCEPTION_SECONDS = 300

UNTRUTHFUL_STATUS_ALIASES = frozenset(
    {
        "complete",
        "completed",
        "done",
        "implemented",
        "tested",
        "successful",
    }
)


class GuardInputError(ValueError):
    """A fail-closed request validation error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _is_opaque_id(value: Any) -> bool:
    return isinstance(value, str) and OPAQUE_ID.fullmatch(value) is not None


def _prohibited_keys(value: Any, *, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            location = f"{prefix}.{key_text}" if prefix else key_text
            if key_text.lower() in PROHIBITED_REQUEST_KEYS:
                found.append(location)
            found.extend(_prohibited_keys(nested, prefix=location))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(_prohibited_keys(nested, prefix=f"{prefix}[{index}]"))
    return found


def _validate_request(request: dict[str, Any]) -> None:
    if request.get("interface_version") != INTERFACE_VERSION:
        raise GuardInputError(
            "INTERFACE_VERSION_MISMATCH",
            f"interface_version must be {INTERFACE_VERSION}",
        )
    for required in ("request_id", "action_id", "action_type"):
        if not _is_opaque_id(request.get(required)):
            raise GuardInputError(
                "INVALID_REQUEST",
                f"{required} must be a bounded opaque identifier",
            )
    forbidden = _prohibited_keys(request)
    if forbidden:
        raise GuardInputError(
            "PRIVATE_FIELD_REFUSED",
            "raw prompts, private content, secrets, and paths are not accepted",
        )

    allowed = {
        "interface_version",
        "request_id",
        "action_id",
        "action_type",
        "delegable_worker_available",
        "scope_id",
        "target_status",
        "evidence",
        "exception_receipt",
        "now",
    }
    unknown = sorted(set(request) - allowed)
    if unknown:
        raise GuardInputError(
            "UNKNOWN_REQUEST_FIELD",
            "unknown request fields are refused",
        )
    if not isinstance(request.get("delegable_worker_available", True), bool):
        raise GuardInputError(
            "INVALID_REQUEST",
            "delegable_worker_available must be boolean",
        )
    if "scope_id" in request and not _is_opaque_id(request["scope_id"]):
        raise GuardInputError(
            "INVALID_REQUEST",
            "scope_id must be a bounded opaque identifier",
        )
    if "now" in request:
        _parse_timestamp(request["now"], "now")
    if "target_status" in request and not _is_opaque_id(
        request["target_status"]
    ):
        raise GuardInputError(
            "INVALID_REQUEST",
            "target_status must be a bounded status token",
        )
    evidence = request.get("evidence", [])
    if not isinstance(evidence, list) or len(evidence) > 16:
        raise GuardInputError(
            "INVALID_REQUEST",
            "evidence must contain at most 16 entries",
        )
    allowed_evidence_fields = {
        "kind",
        "verified",
        "task_id",
        "receipt_id",
        "handback_id",
        "external_thread_id",
        "fencing_token",
        "lease_epoch",
        "policy_snapshot_revision",
        "decision_request_id",
        "gate_fingerprint",
        "route",
        "owner_prompt_required",
    }
    for item in evidence:
        if not isinstance(item, dict):
            raise GuardInputError("INVALID_REQUEST", "evidence entries must be objects")
        if sorted(set(item) - allowed_evidence_fields):
            raise GuardInputError(
                "UNKNOWN_EVIDENCE_FIELD",
                "unknown evidence fields are refused",
            )
        if not _is_opaque_id(item.get("kind")):
            raise GuardInputError(
                "INVALID_REQUEST",
                "evidence.kind must be a bounded token",
            )
        if not isinstance(item.get("verified"), bool):
            raise GuardInputError(
                "INVALID_REQUEST",
                "evidence.verified must be boolean",
            )
        for key, value in item.items():
            if key in {
                "kind",
                "verified",
                "lease_epoch",
                "owner_prompt_required",
            }:
                continue
            if not _is_opaque_id(value):
                raise GuardInputError(
                    "INVALID_REQUEST",
                    f"evidence.{key} must be a bounded opaque identifier",
                )
        if "lease_epoch" in item and (
            not isinstance(item["lease_epoch"], int)
            or isinstance(item["lease_epoch"], bool)
            or item["lease_epoch"] < 1
        ):
            raise GuardInputError(
                "INVALID_REQUEST",
                "evidence.lease_epoch must be a positive integer",
            )
        if "owner_prompt_required" in item and not isinstance(
            item["owner_prompt_required"], bool
        ):
            raise GuardInputError(
                "INVALID_REQUEST",
                "evidence.owner_prompt_required must be boolean",
            )
    if request.get("exception_receipt") is not None:
        _validate_exception_receipt(request["exception_receipt"])


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or len(value) > 40 or not value.endswith("Z"):
        raise GuardInputError(
            "INVALID_REQUEST",
            f"{label} must be an RFC3339 UTC timestamp",
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise GuardInputError(
            "INVALID_REQUEST",
            f"{label} must be an RFC3339 UTC timestamp",
        ) from exc
    if parsed.utcoffset() is None:
        raise GuardInputError(
            "INVALID_REQUEST",
            f"{label} must be an RFC3339 UTC timestamp",
        )
    return parsed


def _validate_exception_receipt(value: Any) -> None:
    if not isinstance(value, dict):
        raise GuardInputError(
            "INVALID_REQUEST", "exception_receipt must be an object"
        )
    required = {
        "receipt_type",
        "receipt_id",
        "action_id",
        "action_type",
        "scope_id",
        "issued_at",
        "expires_at",
        "nondelegable_recovery",
        "eligible_worker_count",
        "authority",
    }
    if set(value) != required:
        raise GuardInputError(
            "INVALID_REQUEST",
            "exception_receipt has invalid fields",
        )
    for key in ("receipt_id", "action_id", "action_type", "scope_id", "authority"):
        if not _is_opaque_id(value[key]):
            raise GuardInputError(
                "INVALID_REQUEST",
                f"exception_receipt.{key} must be a bounded opaque identifier",
            )
    if value["receipt_type"] != "ROOT_EXECUTION_EXCEPTION":
        raise GuardInputError(
            "INVALID_REQUEST",
            "exception_receipt.receipt_type is invalid",
        )
    if not isinstance(value["nondelegable_recovery"], bool):
        raise GuardInputError(
            "INVALID_REQUEST",
            "exception_receipt.nondelegable_recovery must be boolean",
        )
    if (
        not isinstance(value["eligible_worker_count"], int)
        or isinstance(value["eligible_worker_count"], bool)
        or value["eligible_worker_count"] < 0
    ):
        raise GuardInputError(
            "INVALID_REQUEST",
            "exception_receipt.eligible_worker_count must be non-negative",
        )
    _parse_timestamp(value["issued_at"], "exception_receipt.issued_at")
    _parse_timestamp(value["expires_at"], "exception_receipt.expires_at")


def _verified_kinds(request: dict[str, Any]) -> set[str]:
    return {
        item["kind"]
        for item in request.get("evidence", [])
        if item.get("verified") is True
    }


def _has_exact_receipt(request: dict[str, Any]) -> bool:
    required = {
        "task_id",
        "receipt_id",
        "external_thread_id",
        "fencing_token",
        "lease_epoch",
        "policy_snapshot_revision",
    }
    for item in request.get("evidence", []):
        if item.get("kind") != "launch_receipt" or item.get("verified") is not True:
            continue
        if required.issubset(item):
            return True
    return False


def _has_prepare_authorization(request: dict[str, Any]) -> bool:
    required = {
        "task_id",
        "fencing_token",
        "lease_epoch",
        "policy_snapshot_revision",
    }
    for item in request.get("evidence", []):
        if item.get("kind") != "prepare_receipt" or item.get("verified") is not True:
            continue
        if required.issubset(item):
            return True
    return False


def _has_verified_owner_gate(request: dict[str, Any]) -> bool:
    required = {"decision_request_id", "route"}
    for item in request.get("evidence", []):
        if item.get("kind") != "owner_gate" or item.get("verified") is not True:
            continue
        if (
            required.issubset(item)
            and item.get("route") == "OWNER_GATE"
            and item.get("owner_prompt_required") is True
        ):
            return True
    return False


def _valid_execution_exception(request: dict[str, Any]) -> bool:
    receipt = request.get("exception_receipt")
    if receipt is None:
        return False
    if request.get("delegable_worker_available", True):
        return False
    if request.get("scope_id") is None or request.get("now") is None:
        return False
    if (
        receipt["action_id"] != request["action_id"]
        or receipt["action_type"] != request["action_type"]
        or receipt["scope_id"] != request["scope_id"]
        or receipt["authority"] != "SYSTEM_NONDELEGABLE_RECOVERY"
        or receipt["nondelegable_recovery"] is not True
        or receipt["eligible_worker_count"] != 0
    ):
        return False
    issued = _parse_timestamp(receipt["issued_at"], "exception_receipt.issued_at")
    expires = _parse_timestamp(
        receipt["expires_at"], "exception_receipt.expires_at"
    )
    now = _parse_timestamp(request["now"], "now")
    lifetime = (expires - issued).total_seconds()
    return 0 < lifetime <= MAX_EXCEPTION_SECONDS and issued <= now < expires


def _result(
    request: dict[str, Any],
    *,
    classification: str,
    decision: str,
    reason_code: str,
    required_action: str,
    truthful_status: str | None = None,
    exception_receipt_accepted: bool = False,
    owner_notification_authorized: bool = False,
) -> dict[str, Any]:
    return {
        "interface_version": INTERFACE_VERSION,
        "ok": True,
        "operation": "root-role-guard",
        "result": {
            "action_id": request["action_id"],
            "classification": classification,
            "decision": decision,
            "reason_code": reason_code,
            "required_action": required_action,
            "truthful_status": truthful_status,
            "exception_receipt_accepted": exception_receipt_accepted,
            "owner_notification_authorized": owner_notification_authorized,
            "dispatcher_enforcement_required": True,
            "runtime_enforcement_proven": False,
        },
    }


def classify_action(request: dict[str, Any]) -> dict[str, Any]:
    """Classify and authorize one proposed root action without persisting it."""

    _validate_request(request)
    action = request["action_type"]

    if action in TASK_EXECUTION_ACTIONS:
        if _valid_execution_exception(request):
            return _result(
                request,
                classification="TASK_EXECUTION_EXCEPTION",
                decision="ALLOW",
                reason_code="ROOT_EXECUTION_EXCEPTION_ACCEPTED",
                required_action="NONE",
                exception_receipt_accepted=True,
            )
        return _result(
            request,
            classification="TASK_EXECUTION",
            decision="DENY",
            reason_code="ROOT_TASK_EXECUTION_FORBIDDEN",
            required_action="PREPARE_SUCCESSOR_HANDOFF",
        )
    if action not in ORCHESTRATION_ACTIONS:
        return _result(
            request,
            classification="UNKNOWN",
            decision="DENY",
            reason_code="UNKNOWN_ACTION_FAIL_CLOSED",
            required_action="PREPARE_SUCCESSOR_HANDOFF",
        )

    if action == "launch_visible_task" and not _has_prepare_authorization(request):
        return _result(
            request,
            classification="ORCHESTRATION",
            decision="DENY",
            reason_code="PREPARE_AUTHORIZATION_REQUIRED",
            required_action="PREPARE_SUCCESSOR_HANDOFF",
        )

    if action == "refill_capacity" and not _has_exact_receipt(request):
        return _result(
            request,
            classification="ORCHESTRATION",
            decision="DENY",
            reason_code="EXACT_LAUNCH_RECEIPT_REQUIRED",
            required_action="PROVIDE_EXACT_RECEIPT",
        )

    if action == "notify_owner":
        if not _has_verified_owner_gate(request):
            return _result(
                request,
                classification="ORCHESTRATION",
                decision="DENY",
                reason_code="VERIFIED_OWNER_GATE_REQUIRED",
                required_action="PROVIDE_OWNER_GATE_EVIDENCE",
            )
        return _result(
            request,
            classification="ORCHESTRATION",
            decision="ALLOW",
            reason_code="VERIFIED_OWNER_GATE_PRESENT",
            required_action="NONE",
            owner_notification_authorized=True,
        )

    if action == "synthesize_worker_evidence":
        status = request.get("target_status")
        if status in UNTRUTHFUL_STATUS_ALIASES or status not in STATUS_EVIDENCE:
            return _result(
                request,
                classification="ORCHESTRATION",
                decision="DENY",
                reason_code="UNTRUTHFUL_STATUS_FORBIDDEN",
                required_action="PROVIDE_WORKER_EVIDENCE",
            )
        missing = STATUS_EVIDENCE[status] - _verified_kinds(request)
        if missing:
            return _result(
                request,
                classification="ORCHESTRATION",
                decision="DENY",
                reason_code="WORKER_EVIDENCE_REQUIRED",
                required_action="PROVIDE_WORKER_EVIDENCE",
                truthful_status=status,
            )
        return _result(
            request,
            classification="ORCHESTRATION",
            decision="ALLOW",
            reason_code="WORKER_EVIDENCE_CONFIRMED",
            required_action="NONE",
            truthful_status=status,
        )

    return _result(
        request,
        classification="ORCHESTRATION",
        decision="ALLOW",
        reason_code="ROOT_ORCHESTRATION_ALLOWED",
        required_action="NONE",
    )


def _audit_record(
    request: dict[str, Any], response: dict[str, Any], *, sequence: int
) -> dict[str, Any]:
    result = response["result"]
    return {
        "sequence": sequence,
        "action_type": request["action_type"],
        "classification": result["classification"],
        "decision": result["decision"],
        "reason_code": result["reason_code"],
        "required_action": result["required_action"],
        "truthful_status": result["truthful_status"],
        "verified_evidence_kinds": sorted(_verified_kinds(request)),
    }


def _write_audit(state_file: Path, record: dict[str, Any]) -> None:
    state_file = state_file.resolve(strict=False)
    state_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if state_file.exists():
        try:
            payload = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GuardInputError(
                "AUDIT_STATE_CORRUPT",
                "root-role audit state is unreadable or corrupt",
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("interface_version") != INTERFACE_VERSION
            or not isinstance(payload.get("records"), list)
        ):
            raise GuardInputError(
                "AUDIT_STATE_CORRUPT",
                "root-role audit state has an incompatible structure",
            )
        existing = payload["records"]

    records = (existing + [record])[-MAX_AUDIT_RECORDS:]
    payload = {
        "interface_version": INTERFACE_VERSION,
        "records": records,
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{state_file.name}.",
        suffix=".tmp",
        dir=state_file.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, state_file)
        directory_fd = os.open(state_file.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def evaluate_action(
    request: dict[str, Any], *, state_file: Path | None = None
) -> dict[str, Any]:
    """Classify a root action and optionally append a privacy-bounded audit row."""

    response = classify_action(request)
    if state_file is not None:
        record_evaluation(request, response, state_file=state_file)
    return response


def record_evaluation(
    request: dict[str, Any],
    response: dict[str, Any],
    *,
    state_file: Path,
) -> None:
    """Persist one already-finalized, privacy-bounded guard evaluation."""

    if state_file is not None:
        sequence = 1
        if state_file.exists():
            try:
                payload = json.loads(state_file.read_text(encoding="utf-8"))
                records = payload.get("records", [])
                if records:
                    sequence = int(records[-1]["sequence"]) + 1
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                # _write_audit emits the stable fail-closed corruption result.
                pass
        _write_audit(
            state_file,
            _audit_record(request, response, sequence=sequence),
        )


def _error_response(error: GuardInputError) -> dict[str, Any]:
    return {
        "interface_version": INTERFACE_VERSION,
        "ok": False,
        "operation": "root-role-guard",
        "error": {
            "code": error.code,
            "message": str(error),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path)
    parser.add_argument(
        "--request",
        default="-",
        help="JSON request path, or - for stdin",
    )
    parser.add_argument("command", choices=("evaluate",))
    args = parser.parse_args(argv)

    try:
        if args.request == "-":
            request = json.load(sys.stdin)
        else:
            request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise GuardInputError("INVALID_REQUEST", "request must be an object")
        response = evaluate_action(request, state_file=args.state_file)
    except GuardInputError as error:
        json.dump(_error_response(error), sys.stderr, sort_keys=True)
        sys.stderr.write("\n")
        return 2
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        response = _error_response(
            GuardInputError("INVALID_REQUEST", f"request could not be read: {error}")
        )
        json.dump(response, sys.stderr, sort_keys=True)
        sys.stderr.write("\n")
        return 2

    json.dump(response, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
