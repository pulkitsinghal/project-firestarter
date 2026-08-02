"""Shared deterministic fixtures for bridge tests."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
BRIDGE = PLUGIN_ROOT / "skills/pm-proxy-orchestrator/scripts/pm_proxy_bridge.py"
FAKE_SOURCE = PLUGIN_ROOT / "tests/fake_firestarter_cli.py"
SCHEMAS = {
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
    "capacity-watchdog.request.schema.json": "capacity-watchdog-request-1.0.schema.json",
    "capacity-watchdog.response.schema.json": "capacity-watchdog-response-1.0.schema.json",
    "reconcile-external-task.request.schema.json": "reconcile-external-task-request-1.0.schema.json",
    "reconcile-external-task.response.schema.json": "reconcile-external-task-response-1.0.schema.json",
    "duration-estimate.request.schema.json": "duration-estimate-request-1.0.schema.json",
    "duration-estimate.response.schema.json": "duration-estimate-response-1.0.schema.json",
    "duration-schedule.request.schema.json": "duration-schedule-request-1.0.schema.json",
    "duration-schedule.response.schema.json": "duration-schedule-response-1.0.schema.json",
    "record-duration-progress.request.schema.json": "record-duration-progress-request-1.0.schema.json",
    "record-duration-progress.response.schema.json": "record-duration-progress-response-1.0.schema.json",
    "record-duration-observation.request.schema.json": "record-duration-observation-request-1.0.schema.json",
    "record-duration-observation.response.schema.json": "record-duration-observation-response-1.0.schema.json",
    "root-role-guard.request.schema.json": "root-role-guard-request-1.0.schema.json",
    "root-role-guard.response.schema.json": "root-role-guard-response-1.0.schema.json",
}


def temp_parent() -> str | None:
    if sys.platform == "darwin" and Path("/private/tmp").is_dir():
        return "/private/tmp"
    return None


def private_temp(prefix: str) -> Path:
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=temp_parent()))
    os.chmod(path, 0o700)
    return path


def make_fake_install(root: Path, *, version: str = "1.0.0") -> Path:
    cli_root = root / "fake-control"
    schemas = cli_root / "schemas"
    schemas.mkdir(parents=True)
    shutil.copyfile(FAKE_SOURCE, cli_root / "orchestrator_control.py")
    (cli_root / "VERSION").write_text(version + "\n", encoding="utf-8")
    for filename, suffix in SCHEMAS.items():
        (schemas / filename).write_text(
            json.dumps(
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "https://firestarter.invalid/orchestrator-control/" + suffix,
                    "type": "object",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return cli_root / "orchestrator_control.py"


def iso(minutes: int = 0, seconds: int = 0) -> str:
    base = dt.datetime(2026, 7, 28, 22, 0, tzinfo=dt.timezone.utc)
    return (base + dt.timedelta(minutes=minutes, seconds=seconds)).isoformat().replace("+00:00", "Z")


def config_verified_runtime_attestation() -> dict[str, Any]:
    return {
        "root_model": "gpt-5.6-sol",
        "root_reasoning_effort": "xhigh",
        "root_service_tier": "priority",
        "root_fast_mode": True,
        "worker_model": "gpt-5.6-sol",
        "worker_reasoning_effort": "xhigh",
        "worker_service_tier": "priority",
        "worker_fast_mode": True,
        "service_tier_attestation": "config-verified",
        "tier_provenance": "trusted-project-and-user-config",
        "auth_mode": "subscription",
        "history_mode": "bounded",
        "parent_attestation_present": True,
    }


def write_json(path: Path, value: dict[str, Any]) -> Path:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def context(*, action: str = "task-launch") -> dict[str, str]:
    return {
        "owner": "owner-alias",
        "org": "example-org",
        "repo": "example-repo",
        "path": "/",
        "environment": "local",
        "data_class": "synthetic",
        "action": action,
        "task_kind": "implementation",
    }


def recycle_request(*, request_id: str = "recycle-1", now: str | None = None) -> dict[str, Any]:
    return {
        "interface_version": "1.0",
        "request_id": request_id,
        "audits": [],
        "now": now or iso(),
    }


def launch_request(
    *,
    task_id: str = "task-1",
    source_event_key: str = "source-1",
    outcome_key: str = "outcome-1",
    idempotency_key: str = "idem-1",
    prompt: str = "SYNTHETIC_EPHEMERAL_PROMPT_Ω",
    now: str | None = None,
    lease_expires_at: str | None = None,
    repo_root: str = "/synthetic/repo",
    remote: str = "example.invalid/example-org/example-repo",
) -> dict[str, Any]:
    return {
        "interface_version": "1.0",
        "request_id": "prepare-" + task_id,
        "source_event_key": source_event_key,
        "idempotency_key": idempotency_key,
        "outcome_key": outcome_key,
        "task_id": task_id,
        "title": "Synthetic task",
        "prompt": prompt,
        "priority": 500,
        "target": {
            "remote": remote,
            "repo_root": repo_root,
            "path": "/",
            "base_sha": "a" * 40,
            "resource_mode": "repo-wide",
        },
        "context": context(),
        "dependencies": [],
        "permissions": ["read", "scoped-write"],
        "prohibitions": ["secrets", "production"],
        "privacy_boundary": "synthetic-only",
        "evidence_contract": ["typed-checks", "exact-refs"],
        "cleanup_duty": ["retain-remove-manifest"],
        "lease_expires_at": lease_expires_at or iso(minutes=30),
        "now": now or iso(),
    }


def classify_request(
    *,
    action_type: str = "READ_INSPECT",
    gate_type: str = "NONE",
    request_id: str = "decision-1",
) -> dict[str, Any]:
    return {
        "interface_version": "1.0",
        "request_id": request_id,
        "context": context(action="decision"),
        "action_type": action_type,
        "target_alias": "example-target",
        "authorization_scope": "current-task",
        "policy_snapshot_revision": 1,
        "state_revision": 0,
        "authorized": True,
        "reversible": True,
        "destructive": False,
        "external_effect": False,
        "auto_publish": False,
        "identity_change": False,
        "credential_needed": False,
        "cost_change": False,
        "force_or_admin": False,
        "gate_type": gate_type,
        "now": iso(),
    }


def handback_request(
    *,
    task_id: str = "task-1",
    handback_id: str = "handback-1",
    successor: dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    return {
        "interface_version": "1.0",
        "request_id": "request-" + handback_id,
        "handback_id": handback_id,
        "task_id": task_id,
        "policy_snapshot_revision": 1,
        "lease_epoch": 1,
        "fencing_token": 1,
        "disposition": "completed",
        "exact_refs": {
            "base_sha": "a" * 40,
            "candidate_sha": "b" * 40,
            "pr_url": None,
            "merge_sha": None,
            "default_sha": None,
        },
        "checks": [
            {
                "name": "synthetic-unit",
                "scope": "candidate",
                "result": "pass",
                "evidence_ref": "artifact:test-report",
            }
        ],
        "review_findings": [],
        "hosted_ci": {"status": "unexecuted", "steps": 0, "cause": "synthetic"},
        "deployment_state": "not_performed",
        "privacy_boundary": "synthetic-only",
        "artifacts": ["artifact:test-report"],
        "resources": [
            {
                "id": "resource:task-worktree",
                "disposition": "removed",
                "reason": "task-owned synthetic fixture",
                "bytes": 128,
            }
        ],
        "dependencies": [],
        "next_action": "archive predecessor",
        "successor_request": successor,
        "block": None,
        "now": now or iso(minutes=2),
    }


def refill_request(
    *,
    candidates: list[dict[str, Any]] | None = None,
    request_id: str = "refill-1",
    status: str = "completed",
    valid_clean_handback: bool = True,
    capacity: int = 1,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = now or iso(minutes=2)
    return {
        "interface_version": "1.0",
        "request_id": request_id,
        "configured_capacity": capacity,
        "terminal_observation": {
            "status": status,
            "valid_clean_handback": valid_clean_handback,
            "evidence_refs": ["clean-handback", "terminal-observation"],
        },
        "candidates": candidates or [],
        "owner_gates": [],
        "recycle_request": recycle_request(
            request_id="recycle-" + request_id,
            now=timestamp,
        ),
        "now": timestamp,
    }


def policy_rule_request(*, rule_id: str = "R-LEARNED") -> dict[str, Any]:
    return {
        "interface_version": "1.0",
        "request_id": "policy-" + rule_id,
        "expected_policy_revision": 1,
        "rule": {
            "id": rule_id,
            "rule_revision": 1,
            "state": "active",
            "scope": {"owner": "owner-alias", "repo": "example-repo"},
            "precedence_tier": 3,
            "priority": 100,
            "effect": "allow_pm_proxy",
            "directive": {
                "code": "LEARNED_ROUTINE",
                "summary": "Allow scoped reversible routine work.",
                "args": {},
            },
            "gate_code": None,
            "provenance": {
                "source_kind": "owner-decision",
                "source_thread_id": "synthetic-thread",
                "recorded_at": iso(),
                "redacted_summary": "Authenticated scoped synthetic correction.",
            },
            "effective_at": iso(),
            "expires_at": None,
            "supersedes": [],
            "conflict_group": "synthetic-routine",
        },
        "now": iso(),
    }
