#!/usr/bin/env python3
"""Synthetic Firestarter CLI used only by deterministic plugin tests."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


INTERFACE = "1.0"
RUNTIME_POLICY_RECEIPT = {
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
RUNTIME_POLICY_ENVELOPE = {
    "root": {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "service_tier": "priority",
        "fast_mode": True,
    },
    "worker_defaults": {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "service_tier": "priority",
        "fast_mode": True,
    },
}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def identifier(*values: str) -> str:
    return hashlib.sha256("\0".join(values).encode()).hexdigest()[:24]


def emit(operation: str, result: dict[str, Any]) -> int:
    interface = "2.0" if os.environ.get("FAKE_CLI_MODE") == "bad-interface" else INTERFACE
    print(canonical({"interface_version": interface, "ok": True, "operation": operation, "result": result}))
    return 0


def deny(code: str, message: str, status: int, details: dict[str, Any] | None = None) -> int:
    print(
        canonical(
            {
                "interface_version": INTERFACE,
                "ok": False,
                "error": {"code": code, "message": message, "details": details or {}},
            }
        ),
        file=sys.stderr,
    )
    return status


def default_state() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "revision": 0,
        "policy_revision": 1,
        "rules": [
            {"id": "R-PM", "state": "active"},
            {"id": "R-OWNER", "state": "active"},
            {"id": "R-FENCE", "state": "active"},
        ],
        "tasks": {},
        "outbox": {},
        "handbacks": {},
        "recycle_revision": 0,
    }


class LockedState:
    def __init__(self, root: Path):
        self.root = root
        self.state_path = root / "fake-state.json"
        self.lock_path = root / "fake-state.lock"
        self.lock_handle: Any = None
        self.state: dict[str, Any] = {}

    def __enter__(self) -> "LockedState":
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock_handle = self.lock_path.open("a+")
        fcntl.flock(self.lock_handle.fileno(), fcntl.LOCK_EX)
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        else:
            self.state = default_state()
        return self

    def commit(self) -> None:
        descriptor, name = tempfile.mkstemp(prefix=".fake-state-", dir=self.root)
        path = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(canonical(self.state) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(path, self.state_path)
        os.chmod(self.state_path, 0o600)

    def __exit__(self, *_: Any) -> None:
        fcntl.flock(self.lock_handle.fileno(), fcntl.LOCK_UN)
        self.lock_handle.close()


def read_request(path: str | None) -> dict[str, Any]:
    if path != "-":
        return {}
    parsed = json.loads(sys.stdin.read())
    if not isinstance(parsed, dict):
        raise ValueError("request must be object")
    return parsed


def receipt_matches(task: dict[str, Any], request: dict[str, Any]) -> bool:
    return all(
        request.get(key) == task.get(key)
        for key in ("task_id", "policy_snapshot_revision", "lease_epoch", "fencing_token")
    )


def status_result(state: dict[str, Any]) -> dict[str, Any]:
    tasks = [
        {
            "task_id": task["task_id"],
            "state": task["state"],
            "priority": task["priority"],
            "repo_alias": task["target"]["remote"].split("/", 1)[-1],
            "path": task["target"]["path"],
            "updated_at": task["updated_at"],
            "block": task.get("block"),
        }
        for task in state["tasks"].values()
    ]
    outbox = [
        {
            "outbox_id": row["outbox_id"],
            "kind": row["kind"],
            "task_id": row["task_id"],
            "state": row["state"],
            "attempts": 0,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in state["outbox"].values()
    ]
    return {
        "schema_version": state["schema_version"],
        "revision": state["revision"],
        "policy_revision": state["policy_revision"],
        "rules": state["rules"],
        "tasks": sorted(tasks, key=lambda row: row["task_id"]),
        "outbox": sorted(outbox, key=lambda row: row["outbox_id"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("command")
    parser.add_argument("--request")
    parser.add_argument("--now")
    args = parser.parse_args()
    root = Path(args.state_dir)
    mode = os.environ.get("FAKE_CLI_MODE")
    if mode == "locked":
        return deny("STATE_LOCKED", "synthetic lock timeout", 4)
    if mode == "corrupt":
        print("not-json", file=sys.stderr)
        return 4
    request = read_request(args.request)

    with LockedState(root) as authority:
        state = authority.state
        command = args.command

        if command == "init":
            authority.commit()
            return emit("init", {"created": True, "schema_version": "1.0"})
        if command == "status":
            if mode == "quarantine":
                state["rules"].append({"id": "R-CONFLICT", "state": "quarantined"})
            return emit("status", status_result(state))
        if request.get("interface_version") != INTERFACE:
            return deny("SCHEMA_INVALID", "interface mismatch", 2)

        if command == "recycle-queue":
            state["recycle_revision"] += 1
            state["revision"] += 1
            authority.commit()
            return emit(
                command,
                {
                    "ranked_resumable": [],
                    "selected_task_id": None,
                    "archived_task_ids": [],
                    "owner_gated_task_ids": [],
                },
            )

        if command == "prepare-launch":
            if state["recycle_revision"] < 1:
                return deny("RECYCLE_REQUIRED", "queue audit must precede launch", 3)
            time.sleep(float(os.environ.get("FAKE_PREPARE_DELAY", "0")))
            target = request["target"]
            for task in state["tasks"].values():
                overlap = (
                    task["source_event_key"] == request["source_event_key"]
                    or task["outcome_key"] == request["outcome_key"]
                    or task["idempotency_key"] == request["idempotency_key"]
                    or (
                        task["target"]["remote"] == target["remote"]
                        and (
                            task["target"]["resource_mode"] == "repo-wide"
                            or target["resource_mode"] == "repo-wide"
                            or task["target"]["path"] == target["path"]
                            or task["target"]["path"].startswith(target["path"].rstrip("/") + "/")
                            or target["path"].startswith(task["target"]["path"].rstrip("/") + "/")
                        )
                    )
                )
                if overlap and task["state"] not in {"ARCHIVED", "CLOSED"}:
                    return deny(
                        "DUPLICATE_STOP",
                        "canonical owner already reserved",
                        3,
                        {"canonical_task_id": task["task_id"]},
                    )
            rule_ids = ["R-FENCE", "R-OWNER", "R-PM"]
            fence = len(state["tasks"]) + 1
            task = {
                key: request[key]
                for key in (
                    "task_id",
                    "source_event_key",
                    "outcome_key",
                    "idempotency_key",
                    "priority",
                    "target",
                )
            }
            task.update(
                {
                    "state": "LAUNCH_PENDING",
                    "policy_snapshot_revision": state["policy_revision"],
                    "lease_epoch": 1,
                    "fencing_token": fence,
                    "applicable_rule_ids": rule_ids,
                    "lease_expires_at": request["lease_expires_at"],
                    "updated_at": request["now"],
                    "external_thread_id": None,
                    "block": None,
                }
            )
            outbox_id = "create-" + identifier(request["idempotency_key"])
            state["tasks"][task["task_id"]] = task
            state["outbox"][outbox_id] = {
                "outbox_id": outbox_id,
                "kind": "CREATE_THREAD",
                "task_id": task["task_id"],
                "state": "PENDING",
                "created_at": request["now"],
                "updated_at": request["now"],
            }
            state["revision"] += 1
            authority.commit()
            envelope = {
                "envelope_version": "1.0",
                "task_id": task["task_id"],
                "source_event_key": task["source_event_key"],
                "idempotency_key": task["idempotency_key"],
                "outcome_key": task["outcome_key"],
                "issued_at": request["now"],
                "policy_snapshot_revision": task["policy_snapshot_revision"],
                "lease_epoch": task["lease_epoch"],
                "fencing_token": task["fencing_token"],
                "owner_claim_id": "claim-" + task["task_id"],
                "target": target,
                "permissions": request["permissions"],
                "prohibitions": request["prohibitions"],
                "effective_rules": [{"id": rule_id, "directive": {"args": {}}} for rule_id in rule_ids],
                "excluded_rules": [],
                "owner_gate_matrix": {"PM_PROXY": [], "OWNER_GATE": [], "DENY": []},
                "privacy_boundary": request["privacy_boundary"],
                "dependencies": request["dependencies"],
                "evidence_contract": request["evidence_contract"],
                "cleanup_duty": request["cleanup_duty"],
                "heartbeat_protocol": {"command": "record-heartbeat", "requires_current_fence": True},
                "closure_protocol": {"command": "record-handback", "requires_current_fence": True},
                "runtime_policy": RUNTIME_POLICY_ENVELOPE,
                "receipt_required": {
                    "policy_snapshot_revision": task["policy_snapshot_revision"],
                    "applicable_rule_ids": rule_ids,
                    "lease_epoch": task["lease_epoch"],
                    "fencing_token": task["fencing_token"],
                    "runtime_policy": RUNTIME_POLICY_RECEIPT,
                },
            }
            transported = request["prompt"] + "\n\n<orchestrator_launch_envelope>\n" + canonical(envelope) + "\n</orchestrator_launch_envelope>"
            return emit(
                command,
                {
                    "envelope": envelope,
                    "prompt": transported,
                    "outbox": {"outbox_id": outbox_id, "kind": "CREATE_THREAD"},
                },
            )

        if command == "record-launch-receipt":
            task = state["tasks"].get(request.get("task_id"))
            if not task or not receipt_matches(task, request):
                return deny("RECEIPT_MISMATCH", "fabricated or stale receipt", 2)
            if sorted(request.get("applicable_rule_ids", [])) != sorted(task["applicable_rule_ids"]):
                return deny("RECEIPT_MISMATCH", "rule receipt mismatch", 2)
            task["external_thread_id"] = request.get("external_thread_id")
            task["state"] = "RUNNING"
            task["updated_at"] = request["now"]
            for outbox in state["outbox"].values():
                if outbox["task_id"] == task["task_id"] and outbox["kind"] == "CREATE_THREAD":
                    outbox["state"] = "COMPLETE"
                    outbox["updated_at"] = request["now"]
            state["revision"] += 1
            authority.commit()
            return emit(command, {"task_id": task["task_id"], "state": "RUNNING"})

        if command == "record-heartbeat":
            task = state["tasks"].get(request.get("task_id"))
            if not task or task["state"] != "RUNNING" or not receipt_matches(task, request):
                return deny("FENCE_STALE", "current exact receipt is required", 2)
            task["lease_expires_at"] = request["lease_expires_at"]
            task["updated_at"] = request["now"]
            authority.commit()
            return emit(command, {"task_id": task["task_id"], "state": "RUNNING"})

        if command == "classify-decision":
            action = request.get("action_type")
            gate = request.get("gate_type")
            known_routine = {
                "READ_INSPECT",
                "SAFE_RECONCILE",
                "ISOLATED_EDIT_TEST",
                "FOCUSED_BRANCH_COMMIT_PUSH_PR",
                "REVIEW_FIX",
                "NORMAL_MERGE",
                "EXACT_DEFAULT_RETEST",
                "TASK_OWNED_CLEANUP",
                "HOSTED_CI_BILLING_BLOCK",
            }
            if action in known_routine and gate == "NONE":
                route, reason, prompt = "PM_PROXY", "AUTHORIZED_REVERSIBLE_ROUTINE", False
            elif action in {
                "BILLING_CHANGE_OR_SPEND",
                "ACCOUNT_OR_CREDENTIAL_CHANGE",
                "PRODUCTION_CHANGE",
                "EXTERNAL_COMMUNICATION",
                "DESTRUCTIVE_OR_FORCEFUL_CHANGE",
                "PRIVACY_OR_GOVERNED_DATA",
                "HARDWARE_MUTATION",
                "MATERIAL_SCOPE_CHANGE",
            } and gate != "NONE":
                route, reason, prompt = "OWNER_GATE", "ENUMERATED_" + gate, True
            else:
                return deny("DECISION_DENIED", "unknown action returns to orchestrator", 2)
            if mode == "owner-downgrade":
                route, prompt = "OWNER_GATE", False
            return emit(
                command,
                {
                    "classification": route,
                    "reason_code": reason,
                    "rule_ids": ["R-PM"],
                    "reasons": [reason],
                    "owner_prompt_required": prompt,
                    "notification_deduplicated": False,
                },
            )

        if command == "record-policy-rule":
            rule = request["rule"]
            if rule["id"] == "R-CONFLICT":
                state["rules"].append({"id": "R-CONFLICT", "state": "quarantined"})
                state["policy_revision"] += 1
                authority.commit()
                return deny("POLICY_CONFLICT", "equal-precedence conflict quarantined", 3)
            state["rules"].append({"id": rule["id"], "state": "active"})
            state["policy_revision"] += 1
            authority.commit()
            return emit(command, {"rule_id": rule["id"], "policy_revision": state["policy_revision"]})

        if command == "record-handback":
            handback_id = request["handback_id"]
            if handback_id in state["handbacks"]:
                return emit(command, state["handbacks"][handback_id])
            task = state["tasks"].get(request.get("task_id"))
            if not task or task["state"] != "RUNNING" or not receipt_matches(task, request):
                return deny("FENCE_STALE", "current exact receipt is required", 2)
            archive_id = "archive-" + task["task_id"]
            state["outbox"][archive_id] = {
                "outbox_id": archive_id,
                "kind": "ARCHIVE_THREAD",
                "task_id": task["task_id"],
                "state": "PENDING",
                "created_at": request["now"],
                "updated_at": request["now"],
            }
            successor_result = None
            successor = request.get("successor_request")
            if successor is not None:
                successor_id = successor["task_id"]
                create_id = "create-" + identifier(successor["idempotency_key"])
                state["tasks"][successor_id] = {
                    "task_id": successor_id,
                    "source_event_key": successor["source_event_key"],
                    "outcome_key": successor["outcome_key"],
                    "idempotency_key": successor["idempotency_key"],
                    "priority": successor["priority"],
                    "target": successor["target"],
                    "state": "LAUNCH_PENDING",
                    "policy_snapshot_revision": state["policy_revision"],
                    "lease_epoch": 1,
                    "fencing_token": task["fencing_token"] + 1,
                    "applicable_rule_ids": ["R-FENCE", "R-OWNER", "R-PM"],
                    "lease_expires_at": successor["lease_expires_at"],
                    "updated_at": request["now"],
                    "external_thread_id": None,
                    "block": None,
                }
                state["outbox"][create_id] = {
                    "outbox_id": create_id,
                    "kind": "CREATE_THREAD",
                    "task_id": successor_id,
                    "state": "PENDING",
                    "created_at": request["now"],
                    "updated_at": request["now"],
                }
                successor_envelope = {
                    "envelope_version": "1.0",
                    "task_id": successor_id,
                    "source_event_key": successor["source_event_key"],
                    "idempotency_key": successor["idempotency_key"],
                    "outcome_key": successor["outcome_key"],
                    "issued_at": successor["now"],
                    "policy_snapshot_revision": state["policy_revision"],
                    "lease_epoch": 1,
                    "fencing_token": task["fencing_token"] + 1,
                    "owner_claim_id": "claim-" + successor_id,
                    "target": successor["target"],
                    "permissions": successor["permissions"],
                    "prohibitions": successor["prohibitions"],
                    "effective_rules": [
                        {"id": rule_id, "directive": {"args": {}}}
                        for rule_id in ["R-FENCE", "R-OWNER", "R-PM"]
                    ],
                    "excluded_rules": [],
                    "owner_gate_matrix": {"PM_PROXY": [], "OWNER_GATE": [], "DENY": []},
                    "privacy_boundary": successor["privacy_boundary"],
                    "dependencies": successor["dependencies"],
                    "evidence_contract": successor["evidence_contract"],
                    "cleanup_duty": successor["cleanup_duty"],
                    "heartbeat_protocol": {
                        "command": "record-heartbeat",
                        "requires_current_fence": True,
                    },
                    "closure_protocol": {
                        "command": "record-handback",
                        "requires_current_fence": True,
                    },
                    "runtime_policy": RUNTIME_POLICY_ENVELOPE,
                    "receipt_required": {
                        "policy_snapshot_revision": state["policy_revision"],
                        "applicable_rule_ids": ["R-FENCE", "R-OWNER", "R-PM"],
                        "lease_epoch": 1,
                        "fencing_token": task["fencing_token"] + 1,
                        "runtime_policy": RUNTIME_POLICY_RECEIPT,
                    },
                }
                successor_result = {
                    "envelope": successor_envelope,
                    "prompt": (
                        successor["prompt"]
                        + "\n\n<orchestrator_launch_envelope>\n"
                        + canonical(successor_envelope)
                        + "\n</orchestrator_launch_envelope>"
                    ),
                    "outbox": {"outbox_id": create_id, "kind": "CREATE_THREAD"},
                }
            task["state"] = "ARCHIVE_PENDING"
            task["updated_at"] = request["now"]
            result = {
                "task_id": task["task_id"],
                "state": "ARCHIVE_PENDING",
                "archive_outbox_id": archive_id,
                "successor": successor_result,
                "evidence_count": len(request["checks"]),
                "resource_count": len(request["resources"]),
                "reclaimed_bytes": sum(
                    resource.get("bytes", 0)
                    for resource in request["resources"]
                    if resource["disposition"] == "removed"
                ),
            }
            state["handbacks"][handback_id] = result
            state["revision"] += 1
            authority.commit()
            if mode == "crash-after-handback-commit":
                os._exit(9)
            return emit(command, result)

        if command == "record-archive-receipt":
            task = state["tasks"].get(request.get("task_id"))
            if not task or task["state"] != "ARCHIVE_PENDING" or not receipt_matches(task, request):
                return deny("FENCE_STALE", "archive receipt is stale", 2)
            task["state"] = "ARCHIVED"
            task["updated_at"] = request["now"]
            for outbox in state["outbox"].values():
                if outbox["task_id"] == task["task_id"] and outbox["kind"] == "ARCHIVE_THREAD":
                    outbox["state"] = "COMPLETE"
                    outbox["updated_at"] = request["now"]
            authority.commit()
            return emit(command, {"task_id": task["task_id"], "state": "ARCHIVED"})

        if command in {"effective-rules", "takeover-lease"}:
            return emit(command, {})
        return deny("COMMAND_UNKNOWN", "unknown synthetic command", 2)


if __name__ == "__main__":
    raise SystemExit(main())
