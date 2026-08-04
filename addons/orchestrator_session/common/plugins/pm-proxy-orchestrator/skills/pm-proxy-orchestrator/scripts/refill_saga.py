#!/usr/bin/env python3
"""Durable closure/capacity-refill saga layered on Firestarter interface 1.0."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pm_proxy_bridge as bridge


LEDGER_NAME = "pm-proxy-refill-ledger.json"
LOCK_NAME = ".pm-proxy-refill.lock"
TERMINAL_OBSERVATIONS = {"completed", "archived", "interrupted/notLoaded"}
SATISFIED_OUTCOMES = {"REFILL_SATISFIED", "EMPTY", "OWNER_GATED", "CAPACITY_FULL"}
ACTIVE_OR_RESERVED = {"RUNNING", "LAUNCH_PENDING"}
TERMINAL_DISPOSITIONS = {
    "completed",
    "completed_local_only",
    "completed_local_artifact",
    "failed",
    "superseded",
    "duplicate",
}


class SagaLedger:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.path = state_dir / LEDGER_NAME
        self.lock_path = state_dir / LOCK_NAME
        self.handle: Any = None
        self.value: dict[str, Any] = {}

    def __enter__(self) -> "SagaLedger":
        self.handle = self.lock_path.open("a+")
        os.chmod(self.lock_path, 0o600)
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        if self.path.exists():
            self.value = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.value = {"schema_version": "1.0", "sagas": {}}
        if self.value.get("schema_version") != "1.0" or not isinstance(self.value.get("sagas"), dict):
            raise bridge.BridgeError("REFILL_LEDGER_CORRUPT", "refill ledger is incompatible")
        return self

    def commit(self) -> None:
        descriptor, name = tempfile.mkstemp(prefix=".refill-", dir=self.state_dir)
        temporary = Path(name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(bridge.canonical(self.value) + "\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)

    def __exit__(self, *_: Any) -> None:
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


def event(kind: str, now: str, evidence: list[str], **metadata: Any) -> dict[str, Any]:
    return {
        "event": kind,
        "at": now,
        "evidence_refs": sorted(evidence),
        "metadata": metadata,
    }


def load_refill(path_value: str) -> dict[str, Any]:
    request = bridge.load_json_file(path_value, "refill request")
    if request.get("interface_version") != "1.0":
        raise bridge.BridgeError("INTERFACE_INCOMPATIBLE", "refill interface must be 1.0", exit_status=2)
    sanitized = json.loads(bridge.canonical(request))
    for candidate in sanitized.get("candidates", []):
        if isinstance(candidate, dict):
            candidate.pop("prompt", None)
    bridge.scan_strings(sanitized, durable=True)
    capacity = request.get("configured_capacity")
    if not isinstance(capacity, int) or not 1 <= capacity <= 64:
        raise bridge.BridgeError("SCHEMA_INVALID", "configured_capacity must be 1..64", exit_status=2)
    observation = request.get("terminal_observation")
    if not isinstance(observation, dict) or observation.get("status") not in TERMINAL_OBSERVATIONS:
        raise bridge.BridgeError("SCHEMA_INVALID", "terminal observation is unsupported", exit_status=2)
    if observation["status"] == "interrupted/notLoaded" and observation.get("valid_clean_handback") is not True:
        raise bridge.BridgeError(
            "TERMINAL_EVIDENCE_INVALID",
            "interrupted/notLoaded releases capacity only with a valid clean handback",
            exit_status=2,
        )
    evidence = observation.get("evidence_refs")
    if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) for item in evidence):
        raise bridge.BridgeError("TERMINAL_EVIDENCE_INVALID", "terminal evidence refs are required", exit_status=2)
    candidates = request.get("candidates")
    if not isinstance(candidates, list):
        raise bridge.BridgeError("SCHEMA_INVALID", "candidates must be an array", exit_status=2)
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise bridge.BridgeError("SCHEMA_INVALID", "candidate must be an object", exit_status=2)
        bridge.validate_request(candidate, durable=False)
        task_id = candidate.get("task_id")
        if not isinstance(task_id, str) or task_id in seen:
            raise bridge.BridgeError("SCHEMA_INVALID", "candidate task IDs must be unique", exit_status=2)
        seen.add(task_id)
    gates = request.get("owner_gates")
    if not isinstance(gates, list):
        raise bridge.BridgeError("SCHEMA_INVALID", "owner_gates must be an array", exit_status=2)
    return request


def slot_truth(
    status: dict[str, Any],
    refill: dict[str, Any],
    *,
    reserved_task_ids: set[str] | None = None,
) -> dict[str, Any]:
    tasks = status.get("tasks")
    if not isinstance(tasks, list):
        raise bridge.BridgeError("MACHINE_RESPONSE_INVALID", "status tasks are incompatible")
    active = sorted(
        task["task_id"]
        for task in tasks
        if isinstance(task, dict) and task.get("state") in ACTIVE_OR_RESERVED
    )
    reserved = reserved_task_ids or set()
    runnable = sorted(
        (
            candidate
            for candidate in refill["candidates"]
            if candidate["task_id"] not in reserved
        ),
        key=lambda item: (-item["priority"], item["task_id"]),
    )
    capacity = refill["configured_capacity"]
    deficit = max(0, capacity - len(active))
    failure = bool(runnable) and deficit > 0
    return {
        "configured_capacity": capacity,
        "active_or_reserved_count": len(active),
        "active_or_reserved_task_ids": active,
        "runnable_queue_count": len(runnable),
        "runnable_task_ids": [item["task_id"] for item in runnable],
        "deficit": deficit,
        "failure_state": "CAPACITY_DEFICIT" if failure else None,
    }


def exact_terminal_evidence_replay(
    status: dict[str, Any],
    ticket: dict[str, Any],
    handback: dict[str, Any],
) -> bool:
    """Authorize an expired local completion only from exact terminal evidence."""

    receipt = bridge.require_committed_receipt(ticket)
    disposition = handback.get("disposition")
    if disposition not in {"completed_local_only", "completed_local_artifact"}:
        return False
    matching = [
        task
        for task in status.get("tasks", [])
        if isinstance(task, dict) and task.get("task_id") == ticket["task_id"]
    ]
    if len(matching) != 1:
        return False
    task = matching[0]
    lifecycle = task.get("lifecycle")
    hold = task.get("control_schema_hold")
    expected_receipt_fence = {
        "task_id": ticket["task_id"],
        "receipt_external_thread_id": receipt["external_thread_id"],
        "policy_snapshot_revision": ticket["policy_snapshot_revision"],
        "lease_epoch": ticket["lease_epoch"],
        "lease_expires_at": ticket["lease_expires_at"],
        "fencing_token": ticket["fencing_token"],
        "owner_claim_id": ticket["owner_claim_id"],
        "owner_claim_status": "active",
        "claim_lease_epoch": ticket["lease_epoch"],
        "claim_fencing_token": ticket["fencing_token"],
    }
    expected_hold = {
        "hold_state": "CONTROL_SCHEMA_HOLD",
        "ticket_id": ticket["source_event_key"],
        "task_id": ticket["task_id"],
        "external_thread_id": receipt["external_thread_id"],
        "policy_snapshot_revision": ticket["policy_snapshot_revision"],
        "lease_epoch": ticket["lease_epoch"],
        "fencing_token": ticket["fencing_token"],
        "replay_target": disposition,
    }
    exact_identity = (
        task.get("state") == "RUNNING"
        and task.get("canonical_external_thread_id")
        == receipt["external_thread_id"]
        and isinstance(task.get("receipt_fence"), dict)
        and set(task["receipt_fence"]) == set(expected_receipt_fence)
        and task["receipt_fence"] == expected_receipt_fence
        and isinstance(lifecycle, dict)
        and lifecycle.get("task_id") == ticket["task_id"]
    )
    if not exact_identity:
        return False
    if lifecycle.get("lifecycle_state") == "CONTROL_SCHEMA_HOLD":
        return (
            isinstance(hold, dict)
            and set(hold) == set(expected_hold)
            and hold == expected_hold
        )
    expected_action = {
        "COMPLETION_CANDIDATE": "REQUEST_HANDBACK",
        "INTERRUPT_REQUIRED": "TERMINALIZE",
    }.get(lifecycle.get("lifecycle_state"))
    completion_signals = lifecycle.get("completion_signals")
    return (
        expected_action is not None
        and lifecycle.get("required_action") == expected_action
        and isinstance(completion_signals, list)
        and bool(completion_signals)
        and all(isinstance(item, str) and item for item in completion_signals)
        and hold is None
    )


def create_ticket(
    result: dict[str, Any],
    launch: dict[str, Any],
    path: Path,
    schema_version: str,
) -> dict[str, Any]:
    envelope, rule_ids = bridge.validate_prepare_result(result)
    issued = bridge.parse_time(envelope["issued_at"])
    ticket = {
        "ticket_version": bridge.TICKET_VERSION,
        "control_schema_version": schema_version,
        "task_id": envelope["task_id"],
        "source_event_key": envelope["source_event_key"],
        "outcome_key": envelope["outcome_key"],
        "issued_at": envelope["issued_at"],
        "receipt_deadline": bridge.format_time(
            issued + bridge.dt.timedelta(seconds=bridge.LAUNCH_RECEIPT_TTL_SECONDS)
        ),
        "lease_expires_at": launch["lease_expires_at"],
        "policy_snapshot_revision": envelope["policy_snapshot_revision"],
        "lease_epoch": envelope["lease_epoch"],
        "fencing_token": envelope["fencing_token"],
        "applicable_rule_ids": rule_ids,
        "outbox": result["outbox"],
        "receipt": None,
        "last_heartbeat_at": None,
        "handback": None,
        "duration_estimate": envelope.get("duration_estimate"),
        "owner_claim_id": envelope.get("owner_claim_id"),
        "runtime_policy": envelope["receipt_required"]["runtime_policy"],
    }
    bridge.write_ticket_new(path, ticket)
    return ticket


def schedule(
    cli: Path,
    state_dir: Path,
    refill: dict[str, Any],
    saga: dict[str, Any],
    schema_version: str,
) -> list[dict[str, Any]]:
    recycle_result = bridge.run_cli(cli, state_dir, "recycle-queue", request=refill["recycle_request"])
    saga["events"].append(
        event(
            "QUEUE_RECYCLED",
            refill["now"],
            refill["terminal_observation"]["evidence_refs"],
            selected_task_id=recycle_result.get("selected_task_id"),
        )
    )
    current = slot_truth(
        bridge.run_cli(cli, state_dir, "status"),
        refill,
        reserved_task_ids=set(saga.get("reserved_task_ids", [])),
    )
    launches: list[dict[str, Any]] = []
    candidates = sorted(refill["candidates"], key=lambda item: (-item["priority"], item["task_id"]))
    already = set(saga.get("reserved_task_ids", []))
    for candidate in candidates:
        if current["deficit"] <= 0:
            break
        if candidate["task_id"] in already:
            continue
        result = bridge.run_cli(cli, state_dir, "prepare-launch", request=candidate)
        ticket_path = state_dir / f"refill-{candidate['task_id']}.ticket.json"
        ticket = create_ticket(result, candidate, ticket_path, schema_version)
        saga.setdefault("reserved_task_ids", []).append(candidate["task_id"])
        saga.setdefault("receipted_task_ids", [])
        saga["events"].append(
            event(
                "SUCCESSOR_RESERVED",
                refill["now"],
                refill["terminal_observation"]["evidence_refs"],
                task_id=candidate["task_id"],
                outbox_id=result["outbox"]["outbox_id"],
                fencing_token=ticket["fencing_token"],
            )
        )
        launches.append(
            {
                "task_id": candidate["task_id"],
                "prompt": result["prompt"],
                "outbox": result["outbox"],
                "ticket": str(ticket_path),
                "fencing_token": ticket["fencing_token"],
                "applicable_rule_ids": ticket["applicable_rule_ids"],
            }
        )
        current = slot_truth(
            bridge.run_cli(cli, state_dir, "status"),
            refill,
            reserved_task_ids=set(saga.get("reserved_task_ids", [])),
        )
    if launches:
        saga["outcome"] = "SUCCESSOR_RESERVED"
    elif current["deficit"] == 0 and saga.get("reserved_task_ids"):
        saga["outcome"] = "SUCCESSOR_RESERVED"
    elif current["deficit"] == 0:
        saga["outcome"] = "CAPACITY_FULL"
        saga["events"].append(
            event("CAPACITY_FULL", refill["now"], refill["terminal_observation"]["evidence_refs"])
        )
    elif refill["owner_gates"]:
        saga["outcome"] = "OWNER_GATED"
        saga["events"].append(
            event(
                "OWNER_GATED",
                refill["now"],
                sorted(
                    evidence
                    for gate in refill["owner_gates"]
                    for evidence in gate.get("evidence_refs", [])
                ),
            )
        )
    else:
        saga["outcome"] = "EMPTY"
        saga["events"].append(
            event("EMPTY", refill["now"], refill["terminal_observation"]["evidence_refs"])
        )
    final = slot_truth(
        bridge.run_cli(cli, state_dir, "status"),
        refill,
        reserved_task_ids=set(saga.get("reserved_task_ids", [])),
    )
    if final["failure_state"] and len(saga.get("reserved_task_ids", [])) < len(refill["candidates"]):
        saga["events"].append(
            event("CAPACITY_DEFICIT", refill["now"], refill["terminal_observation"]["evidence_refs"], **final)
        )
    saga["slot_truth"] = final
    return launches


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", required=True)
    parser.add_argument("--state-dir", required=True)
    sub = parser.add_subparsers(dest="operation", required=True)
    close = sub.add_parser("close-and-refill")
    close.add_argument("--predecessor-ticket", required=True)
    close.add_argument("--handback-request", required=True)
    close.add_argument("--refill-request", required=True)
    receipt = sub.add_parser("record-refill-receipt")
    receipt.add_argument("--saga-id", required=True)
    receipt.add_argument("--task-id", required=True)
    receipt.add_argument("--external-thread-id", required=True)
    receipt.add_argument("--runtime-attestation", required=True)
    receipt.add_argument("--request-id", required=True)
    receipt.add_argument("--now", required=True)
    watchdog = sub.add_parser("watchdog-refill")
    watchdog.add_argument("--refill-request", required=True)
    status = sub.add_parser("slot-status")
    status.add_argument("--refill-request", required=True)
    return parser


def execute(args: argparse.Namespace) -> dict[str, Any]:
    cli, version = bridge.validate_installation(args.cli)
    state_dir = bridge.validate_private_dir(args.state_dir, "state directory")
    health = bridge.doctor(cli, state_dir, version)
    operation = args.operation
    if operation == "slot-status":
        refill = load_refill(args.refill_request)
        return bridge.success(operation, slot_truth(bridge.run_cli(cli, state_dir, "status"), refill))

    if operation in {"close-and-refill", "watchdog-refill"}:
        refill = load_refill(args.refill_request)
        if refill.get("recycle_request", {}).get("interface_version") != "1.0":
            raise bridge.BridgeError("SCHEMA_INVALID", "recycle_request is required", exit_status=2)
        saga_id = (
            bridge.load_json_file(args.handback_request, "handback request")["handback_id"]
            if operation == "close-and-refill"
            else "watchdog:" + refill["request_id"]
        )
        with SagaLedger(state_dir) as ledger:
            if saga_id in ledger.value["sagas"]:
                existing = ledger.value["sagas"][saga_id]
                return bridge.success(
                    operation,
                    {
                        "saga_id": saga_id,
                        "outcome": existing.get("outcome"),
                        "reserved_task_ids": existing.get("reserved_task_ids", []),
                        "receipted_task_ids": existing.get("receipted_task_ids", []),
                        "launches": [],
                        "slot_truth": existing.get("slot_truth"),
                        "capacity_released": operation == "close-and-refill",
                        "replayed": True,
                        "replay_requires_external_reconciliation": bool(
                            set(existing.get("reserved_task_ids", []))
                            - set(existing.get("receipted_task_ids", []))
                        ),
                    },
                )
            saga = {
                "saga_id": saga_id,
                "predecessor_task_id": None,
                "configured_capacity": refill["configured_capacity"],
                "terminal_observation": refill["terminal_observation"]["status"],
                "outcome": "STARTED",
                "reserved_task_ids": [],
                "receipted_task_ids": [],
                "events": [],
            }
            if operation == "close-and-refill":
                handback = bridge.load_json_file(args.handback_request, "handback request")
                bridge.validate_handback_request(handback)
                predecessor_path, predecessor = bridge.load_ticket(args.predecessor_ticket)
                receipt = bridge.require_committed_receipt(predecessor)
                bridge.inject_ticket_fields(handback, predecessor)
                if bridge.schema_at_least(health["schema_version"], (1, 1)):
                    handback["external_thread_id"] = receipt["external_thread_id"]
                if handback.get("successor_request") is not None:
                    raise bridge.BridgeError(
                        "SCHEMA_INVALID",
                        "close-and-refill owns successor selection; successor_request must be null",
                        exit_status=2,
                    )
                terminal_results = {item["result"] for item in handback.get("checks", [])}
                if handback.get("disposition") not in TERMINAL_DISPOSITIONS:
                    raise bridge.BridgeError("TERMINAL_EVIDENCE_INVALID", "handback is not terminal", exit_status=2)
                if terminal_results & {"fail", "pending", "blocked"}:
                    raise bridge.BridgeError("TERMINAL_EVIDENCE_INVALID", "handback checks are not clean", exit_status=2)
                try:
                    bridge.require_active_receipt(predecessor, handback["now"])
                    firestarter_status = bridge.run_cli(cli, state_dir, "status")
                except bridge.BridgeError as error:
                    if error.code != "RECEIPT_STALE":
                        raise
                    firestarter_status = bridge.run_cli(cli, state_dir, "status")
                    if not exact_terminal_evidence_replay(
                        firestarter_status,
                        predecessor,
                        handback,
                    ):
                        raise error
                before = slot_truth(firestarter_status, refill)
                projected_active = max(0, before["active_or_reserved_count"] - 1)
                candidates = sorted(
                    refill["candidates"],
                    key=lambda item: (-item["priority"], item["task_id"]),
                )
                selected = (
                    candidates[0]
                    if candidates and projected_active < refill["configured_capacity"]
                    else None
                )
                handback["successor_request"] = selected
                schema_version = str(firestarter_status.get("schema_version", "1.0"))
                try:
                    native_capacity = tuple(
                        int(part) for part in schema_version.split(".", 1)
                    ) >= (1, 1)
                except ValueError:
                    raise bridge.BridgeError(
                        "SCHEMA_INCOMPATIBLE",
                        "Firestarter status schema_version is invalid",
                    )
                if native_capacity:
                    handback["capacity"] = {
                        "configured_capacity": refill["configured_capacity"],
                        "runnable_queue_count": len(candidates),
                        "terminal_status": refill["terminal_observation"]["status"],
                        "clean_handback": True,
                        "empty_outcome": (
                            "OWNER_GATED" if refill["owner_gates"] else "EMPTY"
                        ),
                        "evidence_refs": refill["terminal_observation"][
                            "evidence_refs"
                        ],
                        "blocked_audits": refill["recycle_request"].get(
                            "audits", []
                        ),
                    }
                result = bridge.run_cli(cli, state_dir, "record-handback", request=handback)
                predecessor["handback"] = {
                    "recorded_at": handback["now"],
                    "state": result.get("state"),
                }
                bridge.replace_ticket(predecessor_path, predecessor)
                saga["predecessor_task_id"] = predecessor["task_id"]
                saga["archive_outbox_id"] = result.get("archive_outbox_id")
                saga["events"].append(
                    event(
                        "CAPACITY_RELEASED",
                        handback["now"],
                        refill["terminal_observation"]["evidence_refs"],
                        predecessor_task_id=predecessor["task_id"],
                        observed_status=refill["terminal_observation"]["status"],
                        archive_outbox_id=result.get("archive_outbox_id"),
                    )
                )
                if selected is not None:
                    successor_result = result.get("successor")
                    if not isinstance(successor_result, dict):
                        raise bridge.BridgeError(
                            "MACHINE_RESPONSE_INVALID",
                            "handback successor reservation is missing",
                        )
                    successor_ticket = state_dir / f"refill-{selected['task_id']}.ticket.json"
                    ticket = create_ticket(
                        successor_result,
                        selected,
                        successor_ticket,
                        health["schema_version"],
                    )
                    saga["reserved_task_ids"].append(selected["task_id"])
                    saga["events"].append(
                        event(
                            "SUCCESSOR_RESERVED",
                            handback["now"],
                            refill["terminal_observation"]["evidence_refs"],
                            task_id=selected["task_id"],
                            outbox_id=successor_result["outbox"]["outbox_id"],
                            fencing_token=ticket["fencing_token"],
                            phase="closure-transaction",
                        )
                    )
                    saga["outcome"] = "SUCCESSOR_RESERVED"
                    initial_launch = {
                        "task_id": selected["task_id"],
                        "prompt": successor_result["prompt"],
                        "outbox": successor_result["outbox"],
                        "ticket": str(successor_ticket),
                        "fencing_token": ticket["fencing_token"],
                        "applicable_rule_ids": ticket["applicable_rule_ids"],
                    }
                else:
                    initial_launch = None
            launches = schedule(
                cli,
                state_dir,
                refill,
                saga,
                health["schema_version"],
            )
            if operation == "close-and-refill" and initial_launch is not None:
                launches.insert(0, initial_launch)
                saga["outcome"] = "SUCCESSOR_RESERVED"
            ledger.value["sagas"][saga_id] = saga
            ledger.commit()
            return bridge.success(
                operation,
                {
                    "saga_id": saga_id,
                    "outcome": saga["outcome"],
                    "launches": launches,
                    "slot_truth": saga["slot_truth"],
                    "capacity_released": operation == "close-and-refill",
                },
            )

    if operation == "record-refill-receipt":
        bridge.parse_time(args.now)
        runtime_attestation = bridge.validate_runtime_attestation(
            bridge.load_json_file(
                args.runtime_attestation,
                "runtime attestation",
            )
        )
        with SagaLedger(state_dir) as ledger:
            saga = ledger.value["sagas"].get(args.saga_id)
            if not isinstance(saga, dict):
                raise bridge.BridgeError("REFILL_SAGA_MISSING", "refill saga is missing", exit_status=2)
            if args.task_id not in saga.get("reserved_task_ids", []):
                raise bridge.BridgeError("RECEIPT_MISMATCH", "task is not reserved by saga", exit_status=2)
            if args.task_id in saga.get("receipted_task_ids", []):
                ticket_path = state_dir / f"refill-{args.task_id}.ticket.json"
                _, ticket = bridge.load_ticket(str(ticket_path))
                if ticket.get("receipt", {}).get("external_thread_id") != args.external_thread_id:
                    raise bridge.BridgeError(
                        "RECEIPT_CONFLICT",
                        "successor receipt already belongs to a different external task",
                        exit_status=3,
                    )
                return bridge.success(
                    operation,
                    {
                        "task_id": args.task_id,
                        "state": "RUNNING",
                        "saga_id": args.saga_id,
                        "saga_outcome": saga["outcome"],
                        "replayed": True,
                    },
                )
            ticket_path = state_dir / f"refill-{args.task_id}.ticket.json"
            path, ticket = bridge.load_ticket(str(ticket_path))
            bridge.require_fresh_unreceipted(ticket, args.now)
            request = {
                "interface_version": "1.0",
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
            result = bridge.run_cli(cli, state_dir, "record-launch-receipt", request=request)
            ticket["receipt"] = {
                "external_thread_id": args.external_thread_id,
                "recorded_at": args.now,
                "runtime_attestation": runtime_attestation,
            }
            bridge.replace_ticket(path, ticket)
            saga["receipted_task_ids"].append(args.task_id)
            saga["events"].append(
                event(
                    "SUCCESSOR_RECEIPTED",
                    args.now,
                    [f"receipt:{args.request_id}"],
                    task_id=args.task_id,
                )
            )
            if sorted(saga["receipted_task_ids"]) == sorted(saga["reserved_task_ids"]):
                saga["outcome"] = "REFILL_SATISFIED"
            ledger.commit()
            return bridge.success(
                operation,
                {
                    **result,
                    "saga_id": args.saga_id,
                    "saga_outcome": saga["outcome"],
                },
            )
    raise bridge.BridgeError("COMMAND_DENIED", "unsupported refill operation", exit_status=2)


def main() -> int:
    try:
        response = execute(build_parser().parse_args())
    except bridge.BridgeError as error:
        bridge.emit(bridge.fail_payload(error), stream=sys.stderr)
        return error.exit_status
    except Exception:
        error = bridge.BridgeError("REFILL_SAGA_FAILURE", "unexpected local refill failure")
        bridge.emit(bridge.fail_payload(error), stream=sys.stderr)
        return error.exit_status
    bridge.emit(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
