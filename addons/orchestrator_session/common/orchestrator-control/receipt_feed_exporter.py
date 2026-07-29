#!/usr/bin/env python3
"""Build a privacy-safe dashboard receipt feed from Firestarter status.

The adapter is deliberately separate from ``orchestrator_control.py``. It reads
an authoritative status response plus an allowlist-only local join map, creates
fresh projection objects, validates semantic invariants, and writes no state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


MAX_JSON_BYTES = 1_048_576
INTERFACE_VERSION = "1.0"
FEED_VERSION = "1.0"
FIRESTARTER_SCHEMA = "1.2"
SNAPSHOT_PREFIX = "receipt-feed-1.0."
CURRENT_POINTER = "receipt-feed-current.json"
PREVIOUS_POINTER = "receipt-feed-previous.json"
LIFECYCLES = {
    "setup-reserved",
    "active",
    "waiting",
    "owner-gated",
    "failed",
    "done",
    "acknowledged",
}
GATE_KINDS = {"none", "dependency", "owner", "external", "capacity", "failure"}
EVIDENCE_KINDS = {
    "receipt",
    "test",
    "commit",
    "pullRequest",
    "deployment",
    "decision",
    "artifact",
}
SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{0,127}$")
SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#@+-]{0,159}$")
FINGERPRINT = re.compile(r"^rcpt_[a-f0-9]{64}$")
PRIVATE_UUID = re.compile(
    r"(?:^|[^a-f0-9])[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-"
    r"[89ab][a-f0-9]{3}-[a-f0-9]{12}(?:$|[^a-f0-9])",
    re.IGNORECASE,
)
EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
SECRET = re.compile(
    r"(?i)(?:password|passwd|secret|api[-_]?key|access[-_]?token|bearer)"
    r"\s*[:=]\s*\S+"
)
ABSOLUTE_PATH = re.compile(r"(?:^|[\s\"'])(?:/Users/|/home/|/private/|[A-Za-z]:\\)")
STATE_TO_LIFECYCLE = {
    "LAUNCH_PENDING": "setup-reserved",
    "RUNNING": "active",
    "BLOCKED": "waiting",
    "FAILED": "failed",
    "CLOSING": "done",
    "CLOSED": "done",
    "ARCHIVE_PENDING": "done",
    "ARCHIVED": "acknowledged",
}
NEXT_SAFE_MOVE = {
    "setup-reserved": "await-launch-receipt",
    "active": "continue-active-work",
    "waiting": "resolve-dependency",
    "owner-gated": "review-owner-gate",
    "failed": "retry-or-reconcile-failure",
    "done": "verify-and-archive",
    "acknowledged": "none-terminal",
}


class ExportError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def fail(code: str, message: str) -> None:
    raise ExportError(code, message)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def strict_object(
    value: Any,
    required: set[str],
    optional: set[str] | None = None,
    *,
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail("INPUT_INVALID", f"{label} must be an object")
    allowed = required | (optional or set())
    if set(value) - allowed or not required.issubset(value):
        fail("INPUT_INVALID", f"{label} has invalid fields")
    return value


def sanitized_identity(value: Any) -> dict[str, str]:
    identity = strict_object(
        value,
        {"sourceEventKey", "outcomeKey", "receiptKind", "canonicalOwnerKey"},
        label="taskFacts.identity",
    )
    result: dict[str, str] = {}
    for key, item in identity.items():
        if (
            not isinstance(item, str)
            or not SAFE_ID.fullmatch(item)
            or ".." in item
            or PRIVATE_UUID.search(item)
            or EMAIL.search(item)
        ):
            fail("PRIVACY_REJECTED", f"identity.{key} is not a coarse safe label")
        result[key] = item
    return result


def fingerprint_of(identity: dict[str, str], *, kind: str | None = None) -> str:
    material = [
        "dashboard-receipt-feed/1.0",
        identity["sourceEventKey"],
        identity["outcomeKey"],
        kind or identity["receiptKind"],
        identity["canonicalOwnerKey"],
    ]
    digest = hashlib.sha256(canonical(material).encode("ascii")).hexdigest()
    return f"rcpt_{digest}"


def unsafe_text(value: str) -> bool:
    return bool(
        PRIVATE_UUID.search(value)
        or EMAIL.search(value)
        or SECRET.search(value)
        or ABSOLUTE_PATH.search(value)
        or "://" in value
        or "-----BEGIN" in value
    )


def sanitize_evidence(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 24:
        fail("PRIVACY_REJECTED", "evidence must be a bounded list")
    output: list[dict[str, str]] = []
    for raw in value:
        item = strict_object(raw, {"kind", "ref"}, {"label"}, label="evidence item")
        kind = item["kind"]
        ref = item["ref"]
        label = item.get("label")
        if kind not in EVIDENCE_KINDS:
            fail("PRIVACY_REJECTED", "evidence kind is not allowlisted")
        if (
            not isinstance(ref, str)
            or not SAFE_REF.fullmatch(ref)
            or ref.startswith(("/", "~"))
            or ".." in ref
            or "\\" in ref
            or "?" in ref
            or unsafe_text(ref)
            or re.match(r"(?i)^(?:raw[-_]?prompt|prompt|credential):", ref)
        ):
            fail("PRIVACY_REJECTED", "evidence ref is unsafe")
        result = {"kind": kind, "ref": ref}
        if label is not None:
            if (
                not isinstance(label, str)
                or len(label) > 120
                or any(char in label for char in "\r\n<>")
                or unsafe_text(label)
            ):
                fail("PRIVACY_REJECTED", "evidence label is unsafe")
            result["label"] = label
        output.append(result)
    return output


def metric(value: Any, availability: str = "derived") -> dict[str, Any]:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return {"value": value, "availability": availability}
    return {"value": None, "availability": "unavailable"}


def duration_projection(task: dict[str, Any]) -> dict[str, Any]:
    duration = task.get("duration")
    if not isinstance(duration, dict):
        return {
            "estimateSeconds": metric(None),
            "elapsedActiveSeconds": metric(None),
            "externalWaitSeconds": metric(None),
            "firstUsefulEvidenceSeconds": metric(None),
        }
    expected = duration.get("expected_components")
    estimate = None
    if isinstance(expected, dict):
        setup = expected.get("setup_seconds")
        tests = expected.get("test_seconds")
        if all(isinstance(item, int) and not isinstance(item, bool) for item in (setup, tests)):
            estimate = setup + tests
    actual = duration.get("actual")
    actual = actual if isinstance(actual, dict) else {}
    return {
        "estimateSeconds": metric(estimate),
        "elapsedActiveSeconds": metric(actual.get("active_seconds")),
        "externalWaitSeconds": metric(actual.get("external_wait_seconds")),
        "firstUsefulEvidenceSeconds": metric(actual.get("first_evidence_seconds")),
    }


def gate_for(task: dict[str, Any], fact: dict[str, Any], lifecycle: str) -> str:
    supplied = fact.get("gateKind")
    if supplied is not None and supplied not in GATE_KINDS:
        fail("INPUT_INVALID", "taskFacts.gateKind is invalid")
    block = task.get("block")
    classification = block.get("classification") if isinstance(block, dict) else None
    if classification == "owner_gate":
        derived = "owner"
    elif classification == "external_dependency":
        derived = "external"
    elif classification == "dependency":
        derived = "dependency"
    elif lifecycle == "failed":
        derived = "failure"
    else:
        derived = "none"
    gate = supplied or derived
    if lifecycle == "owner-gated" and gate != "owner":
        fail("OWNER_GATE_MISMATCH", "owner-gated lifecycle requires owner gate")
    if gate == "owner" and lifecycle != "owner-gated":
        fail("OWNER_GATE_MISMATCH", "owner gate requires owner-gated lifecycle")
    return gate


def lifecycle_for(task: dict[str, Any], fact: dict[str, Any]) -> str:
    state = task.get("state")
    if state == "DUPLICATE_STOP":
        return "failed"
    lifecycle = STATE_TO_LIFECYCLE.get(state)
    if lifecycle is None:
        fail("STATE_UNSUPPORTED", f"task state {state!r} has no receipt projection")
    block = task.get("block")
    if (
        state == "BLOCKED"
        and isinstance(block, dict)
        and block.get("classification") == "owner_gate"
    ):
        return "owner-gated"
    if state == "RUNNING" and not task.get("canonical_external_thread_id"):
        fail("RECEIPT_REQUIRED", "RUNNING task lacks a canonical launch receipt")
    return lifecycle


def configured_capacity(status: dict[str, Any]) -> int | None:
    rows = status.get("capacity")
    if not isinstance(rows, list):
        return None
    values = {
        row.get("configured_capacity")
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("configured_capacity"), int)
        and not isinstance(row.get("configured_capacity"), bool)
        and row.get("configured_capacity") >= 0
    }
    if len(values) > 1:
        fail("CAPACITY_CONFLICT", "authoritative capacity rows disagree")
    return next(iter(values)) if values else None


def normalize_fact(raw: Any) -> dict[str, Any]:
    fact = strict_object(
        raw,
        {"taskKey", "identity", "revision"},
        {
            "gateKind",
            "dependsOnTaskKeys",
            "successorTaskKeys",
            "terminalLeaf",
            "mirrorOfTaskKey",
            "evidence",
            "acceptanceEvidence",
            "role",
        },
        label="taskFacts item",
    )
    if not isinstance(fact["taskKey"], str) or not fact["taskKey"]:
        fail("INPUT_INVALID", "taskFacts.taskKey is invalid")
    if not isinstance(fact["revision"], int) or isinstance(fact["revision"], bool) or fact["revision"] < 1:
        fail("INPUT_INVALID", "taskFacts.revision is invalid")
    if fact.get("role", "worker") != "worker":
        fail("ROOT_INCLUDED", "root cannot appear in the worker receipt feed")
    output = {
        "taskKey": fact["taskKey"],
        "identity": sanitized_identity(fact["identity"]),
        "revision": fact["revision"],
        "gateKind": fact.get("gateKind"),
        "dependsOnTaskKeys": fact.get("dependsOnTaskKeys", []),
        "successorTaskKeys": fact.get("successorTaskKeys", []),
        "terminalLeaf": fact.get("terminalLeaf", False),
        "mirrorOfTaskKey": fact.get("mirrorOfTaskKey"),
        "evidence": sanitize_evidence(fact.get("evidence", [])),
        "acceptanceEvidence": sanitize_evidence(fact.get("acceptanceEvidence", [])),
    }
    for key in ("dependsOnTaskKeys", "successorTaskKeys"):
        values = output[key]
        if (
            not isinstance(values, list)
            or len(values) > 64
            or any(not isinstance(item, str) or not item for item in values)
            or len(values) != len(set(values))
        ):
            fail("INPUT_INVALID", f"taskFacts.{key} is invalid")
    if not isinstance(output["terminalLeaf"], bool):
        fail("INPUT_INVALID", "taskFacts.terminalLeaf must be boolean")
    mirror = output["mirrorOfTaskKey"]
    if mirror is not None and (not isinstance(mirror, str) or not mirror):
        fail("INPUT_INVALID", "taskFacts.mirrorOfTaskKey is invalid")
    return output


def derive_discrepancies(
    status: dict[str, Any],
    *,
    active: int,
    setup_reserved: int,
) -> set[str]:
    discrepancies: set[str] = set()
    duration = status.get("duration")
    if isinstance(duration, dict):
        active_counts = duration.get("receipt_backed_lane_counts")
        reserved_counts = duration.get("reserved_setup_lane_counts")
        if isinstance(active_counts, dict) and sum(
            value for value in active_counts.values() if isinstance(value, int)
        ) != active:
            discrepancies.add("SUPPLIED_DERIVED_MISMATCH")
        if isinstance(reserved_counts, dict) and sum(
            value for value in reserved_counts.values() if isinstance(value, int)
        ) != setup_reserved:
            discrepancies.add("SUPPLIED_DERIVED_MISMATCH")
    capacity = status.get("capacity")
    if isinstance(capacity, list) and capacity:
        latest = capacity[-1]
        if isinstance(latest, dict):
            if latest.get("active_count") not in (None, active):
                discrepancies.add("SUPPLIED_DERIVED_MISMATCH")
            if latest.get("reserved_setup_count") not in (None, setup_reserved):
                discrepancies.add("SUPPLIED_DERIVED_MISMATCH")
    if status.get("capacity_failure") is True:
        discrepancies.add("CAPACITY_INVARIANT_FAILED")
    return discrepancies


def export_feed(raw: Any) -> dict[str, Any]:
    request = strict_object(
        raw,
        {
            "interfaceVersion",
            "servedAt",
            "freshnessThresholdSeconds",
            "status",
            "taskFacts",
        },
        label="export request",
    )
    if request["interfaceVersion"] != INTERFACE_VERSION:
        fail("VERSION_UNSUPPORTED", "export interface version is unsupported")
    served = parse_time(request["servedAt"])
    threshold = request["freshnessThresholdSeconds"]
    if served is None:
        fail("INPUT_INVALID", "servedAt must be an RFC3339 timestamp")
    if not isinstance(threshold, int) or isinstance(threshold, bool) or not 1 <= threshold <= 86_400:
        fail("INPUT_INVALID", "freshnessThresholdSeconds is invalid")
    response = request["status"]
    if (
        not isinstance(response, dict)
        or response.get("ok") is not True
        or response.get("operation") != "status"
        or not isinstance(response.get("result"), dict)
    ):
        fail("STATUS_INVALID", "expected a successful authoritative status response")
    status = response["result"]
    if status.get("schema_version") != FIRESTARTER_SCHEMA:
        fail("VERSION_UNSUPPORTED", "Firestarter status schema must be 1.2")
    duration_status = status.get("duration")
    if (
        not isinstance(duration_status, dict)
        or duration_status.get("root_excluded_from_worker_capacity") is not True
    ):
        fail("ROOT_INCLUDED", "authoritative status must exclude root")

    facts_raw = request["taskFacts"]
    if not isinstance(facts_raw, list) or len(facts_raw) > 2_000:
        fail("INPUT_INVALID", "taskFacts must be a bounded list")
    facts = [normalize_fact(item) for item in facts_raw]
    fact_by_key = {item["taskKey"]: item for item in facts}
    if len(fact_by_key) != len(facts):
        fail("INPUT_INVALID", "taskFacts.taskKey must be unique")
    tasks = status.get("tasks")
    if not isinstance(tasks, list):
        fail("STATUS_INVALID", "status.tasks must be an array")
    task_by_key = {
        task.get("task_id"): task
        for task in tasks
        if isinstance(task, dict) and isinstance(task.get("task_id"), str)
    }
    if set(task_by_key) != set(fact_by_key):
        fail("IDENTITY_UNAVAILABLE", "every status task requires exactly one sanitized fact")

    fingerprints = {
        key: fingerprint_of(fact["identity"]) for key, fact in fact_by_key.items()
    }
    projected: list[dict[str, Any]] = []
    for key in sorted(task_by_key):
        task = task_by_key[key]
        fact = fact_by_key[key]
        lifecycle = lifecycle_for(task, fact)
        gate = gate_for(task, fact, lifecycle)
        unresolved_dependencies = [
            dep for dep in fact["dependsOnTaskKeys"] if dep not in fingerprints
        ]
        unresolved_successors = [
            successor
            for successor in fact["successorTaskKeys"]
            if successor not in fingerprints
        ]
        depends_on = sorted(
            fingerprints[item]
            for item in fact["dependsOnTaskKeys"]
            if item in fingerprints
        )
        successors = sorted(
            fingerprints[item]
            for item in fact["successorTaskKeys"]
            if item in fingerprints
        )
        acceptance = (
            [fingerprint_of(fact["identity"], kind="acceptance")]
            if fact["acceptanceEvidence"]
            else []
        )
        evidence = fact["evidence"] + fact["acceptanceEvidence"]
        if lifecycle in {"done", "acknowledged"} and not acceptance:
            fail("CLOSE_WITHOUT_ACCEPTANCE", "terminal task requires acceptance evidence")
        terminal_leaf = fact["terminalLeaf"]
        leaf_evidence = any(
            item["kind"] == "decision"
            and item["ref"]
            in {
                "decision:terminal-leaf",
                "decision:capacity-full",
                "decision:owner-gated",
            }
            for item in evidence
        )
        if terminal_leaf and not leaf_evidence:
            fail("CLOSE_WITHOUT_SUCCESSOR", "terminal leaf requires explicit decision evidence")
        if lifecycle in {"done", "acknowledged"} and not successors and not terminal_leaf:
            fail("CLOSE_WITHOUT_SUCCESSOR", "non-leaf terminal task requires a successor")
        if unresolved_successors and lifecycle in {"done", "acknowledged"}:
            fail("CLOSE_WITHOUT_SUCCESSOR", "terminal successor identity is unavailable")
        item = {
            "fingerprint": fingerprints[key],
            "revision": fact["revision"],
            "lifecycle": lifecycle,
            "gateKind": gate,
            "dependsOn": depends_on,
            "acceptanceReceipts": acceptance,
            "successorReceipts": successors,
            "runnable": None,
            "nextSafeMove": NEXT_SAFE_MOVE[lifecycle],
            "duration": duration_projection(task),
            "fieldAvailability": {
                "lifecycle": "derived",
                "gateKind": "supplied" if fact["gateKind"] is not None else "derived",
                "dependsOn": (
                    "unavailable" if unresolved_dependencies else "supplied"
                ),
                "successorReceipts": (
                    "unavailable" if unresolved_successors else "supplied"
                ),
                "runnable": "derived",
                "duration.estimateSeconds": duration_projection(task)[
                    "estimateSeconds"
                ]["availability"],
                "duration.elapsedActiveSeconds": duration_projection(task)[
                    "elapsedActiveSeconds"
                ]["availability"],
                "duration.externalWaitSeconds": duration_projection(task)[
                    "externalWaitSeconds"
                ]["availability"],
                "duration.firstUsefulEvidenceSeconds": duration_projection(task)[
                    "firstUsefulEvidenceSeconds"
                ]["availability"],
            },
            "evidenceRefs": evidence,
            "_unresolvedDependencies": bool(unresolved_dependencies),
            "_sourceState": task.get("state"),
        }
        mirror_key = fact["mirrorOfTaskKey"]
        if mirror_key is not None:
            if mirror_key not in fingerprints:
                fail("IDENTITY_UNAVAILABLE", "mirror canonical identity is unavailable")
            item["mirrorOf"] = fingerprints[mirror_key]
        if task.get("state") == "DUPLICATE_STOP" and "mirrorOf" not in item:
            fail("MIRROR_UNMARKED", "duplicate-stop task requires mirrorOf")
        projected.append(item)

    quarantine: list[dict[str, Any]] = []
    canonical_receipts: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in projected:
        groups[item["fingerprint"]].append(item)
    for fingerprint, group in sorted(groups.items()):
        mirrors = [item for item in group if "mirrorOf" in item]
        canonical_group = [item for item in group if "mirrorOf" not in item]
        for item in mirrors:
            quarantine.append(
                {
                    "fingerprint": fingerprint,
                    "reason": "mirror",
                    "mirrorOf": item["mirrorOf"],
                    "excludedFromCounts": True,
                }
            )
        by_revision: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for item in canonical_group:
            by_revision[item["revision"]].append(item)
        conflicted = False
        for revision_group in by_revision.values():
            if len(revision_group) > 1:
                conflicted = True
                for _ in revision_group:
                    quarantine.append(
                        {
                            "fingerprint": fingerprint,
                            "reason": "duplicate-without-mirrorOf",
                            "mirrorOf": None,
                            "excludedFromCounts": True,
                        }
                    )
        if conflicted:
            continue
        if canonical_group:
            canonical_receipts.append(
                max(canonical_group, key=lambda item: item["revision"])
            )

    receipt_by_fingerprint = {
        item["fingerprint"]: item for item in canonical_receipts
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(fingerprint: str) -> None:
        if fingerprint in visiting:
            fail("DEPENDENCY_CYCLE", "receipt dependency cycle")
        if fingerprint in visited:
            return
        visiting.add(fingerprint)
        for dependency in receipt_by_fingerprint[fingerprint]["dependsOn"]:
            if dependency in receipt_by_fingerprint:
                visit(dependency)
        visiting.remove(fingerprint)
        visited.add(fingerprint)

    for fingerprint in sorted(receipt_by_fingerprint):
        visit(fingerprint)

    configured = configured_capacity(status)
    active = sum(item["lifecycle"] == "active" for item in canonical_receipts)
    reserved = sum(
        item["lifecycle"] == "setup-reserved" for item in canonical_receipts
    )
    occupied = active + reserved
    for item in canonical_receipts:
        dependencies = [
            receipt_by_fingerprint.get(dependency)
            for dependency in item["dependsOn"]
        ]
        dependencies_known = (
            not item.pop("_unresolvedDependencies")
            and all(dependency is not None for dependency in dependencies)
        )
        dependencies_done = dependencies_known and all(
            dependency["lifecycle"] in {"done", "acknowledged"}
            for dependency in dependencies
        )
        if configured is None or not dependencies_known:
            item["runnable"] = None
            item["fieldAvailability"]["runnable"] = "unavailable"
        else:
            item["runnable"] = (
                item["lifecycle"] in {"setup-reserved", "waiting"}
                and item["gateKind"] in {"none", "dependency", "capacity"}
                and dependencies_done
                and occupied < configured
            )
        item.pop("_sourceState")

    counts_by_state = Counter(item["lifecycle"] for item in canonical_receipts)
    counts = {
        "availability": "derived",
        "setupReserved": counts_by_state["setup-reserved"],
        "active": counts_by_state["active"],
        "waiting": counts_by_state["waiting"],
        "ownerGated": counts_by_state["owner-gated"],
        "failed": counts_by_state["failed"],
        "done": counts_by_state["done"],
        "acknowledged": counts_by_state["acknowledged"],
        "runnable": (
            None
            if any(item["runnable"] is None for item in canonical_receipts)
            else sum(item["runnable"] is True for item in canonical_receipts)
        ),
        "quarantined": len(quarantine),
    }
    discrepancies = derive_discrepancies(
        status, active=counts["active"], setup_reserved=counts["setupReserved"]
    )
    if quarantine:
        discrepancies.add("MIRROR_QUARANTINED")
    if any(
        item["reason"] == "duplicate-without-mirrorOf" for item in quarantine
    ):
        discrepancies.add("RECEIPT_REVISION_CONFLICT")

    generated_at = duration_status.get("freshness", {}).get("evaluated_at")
    generated = parse_time(generated_at)
    known_time = generated is not None and generated <= served
    age_seconds = (
        int((served - generated).total_seconds()) if known_time and generated else None
    )
    freshness = (
        "unknown"
        if age_seconds is None
        else ("current" if age_seconds <= threshold else "stale")
    )
    if freshness == "stale":
        discrepancies.add("STALE_SOURCE")
    stale_tasks = any(
        isinstance(task.get("freshness"), dict)
        and task["freshness"].get("stale") is True
        for task in tasks
    )
    if stale_tasks:
        discrepancies.add("STALE_SOURCE")
    source_status = (
        "invalid"
        if freshness == "unknown"
        else (
            "degraded"
            if freshness == "stale" or discrepancies
            else "live"
        )
    )
    revision = status.get("revision")
    source_revision = (
        f"status-{revision}"
        if isinstance(revision, int) and not isinstance(revision, bool) and revision >= 0
        else None
    )
    feed = {
        "schemaVersion": FEED_VERSION,
        "source": {
            "generatedAt": generated_at if known_time else None,
            "servedAt": request["servedAt"],
            "sourceStatus": source_status,
            "freshness": {
                "state": freshness,
                "ageSeconds": age_seconds,
                "thresholdSeconds": threshold,
            },
            "sourceRevision": source_revision,
            "discrepancies": sorted(discrepancies),
        },
        "capacity": {
            "configuredWorkers": configured,
            "rootExcluded": True,
            "availability": "derived" if configured is not None else "unavailable",
        },
        "counts": counts,
        "receipts": sorted(
            canonical_receipts,
            key=lambda item: (item["fingerprint"], item["revision"]),
        ),
        "ownerGates": [],
        "quarantine": quarantine,
    }
    validate_feed(feed)
    return feed


def validate_feed(feed: Any) -> None:
    if not isinstance(feed, dict) or set(feed) != {
        "schemaVersion",
        "source",
        "capacity",
        "counts",
        "receipts",
        "ownerGates",
        "quarantine",
    }:
        fail("FEED_INVALID", "feed has invalid top-level fields")
    if feed["schemaVersion"] != FEED_VERSION:
        fail("FEED_INVALID", "feed schemaVersion is invalid")
    source = feed["source"]
    if source.get("sourceStatus") not in {"live", "degraded", "unavailable", "invalid"}:
        fail("FEED_INVALID", "feed sourceStatus is invalid")
    if source.get("freshness", {}).get("state") not in {"current", "stale", "unknown"}:
        fail("FEED_INVALID", "feed freshness is invalid")
    if feed["capacity"].get("rootExcluded") is not True:
        fail("FEED_INVALID", "feed capacity includes root")
    seen: set[tuple[str, int]] = set()
    by_fingerprint: dict[str, dict[str, Any]] = {}
    for receipt in feed["receipts"]:
        key = (receipt.get("fingerprint"), receipt.get("revision"))
        if (
            not isinstance(key[0], str)
            or not FINGERPRINT.fullmatch(key[0])
            or not isinstance(key[1], int)
            or key[1] < 1
            or key in seen
        ):
            fail("FEED_INVALID", "receipt identity/revision is invalid")
        seen.add(key)
        by_fingerprint[key[0]] = receipt
        if receipt.get("lifecycle") not in LIFECYCLES:
            fail("FEED_INVALID", "receipt lifecycle is invalid")
        if receipt.get("gateKind") not in GATE_KINDS:
            fail("FEED_INVALID", "receipt gateKind is invalid")
        if receipt.get("nextSafeMove") != NEXT_SAFE_MOVE[receipt["lifecycle"]]:
            fail("FEED_INVALID", "receipt nextSafeMove is invalid")
        if receipt["lifecycle"] == "owner-gated" and receipt["gateKind"] != "owner":
            fail("FEED_INVALID", "owner action is not explicitly owner-gated")
        if receipt["gateKind"] == "owner" and receipt["lifecycle"] != "owner-gated":
            fail("FEED_INVALID", "owner gate escaped owner-gated lifecycle")
        sanitize_evidence(receipt.get("evidenceRefs"))
        for value in receipt.get("duration", {}).values():
            if (
                not isinstance(value, dict)
                or value.get("availability") not in {
                    "supplied",
                    "derived",
                    "unavailable",
                }
                or (
                    value.get("availability") == "unavailable"
                    and value.get("value") is not None
                )
            ):
                fail("FEED_INVALID", "duration availability is invalid")
    for receipt in feed["receipts"]:
        for dependency in receipt["dependsOn"]:
            if dependency not in by_fingerprint:
                fail("FEED_INVALID", "feed contains an unresolved dependency fingerprint")
    seen_gates: set[str] = set()
    for gate in feed["ownerGates"]:
        fingerprint = gate.get("fingerprint")
        if (
            not isinstance(fingerprint, str)
            or not FINGERPRINT.fullmatch(fingerprint)
            or fingerprint in seen_gates
            or gate.get("nextSafeMove") != "review-owner-gate"
            or not isinstance(gate.get("revision"), int)
            or gate["revision"] < 1
            or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", gate.get("decisionCode", ""))
            or parse_time(gate.get("recordedAt")) is None
        ):
            fail("FEED_INVALID", "owner gate projection is invalid")
        seen_gates.add(fingerprint)
        sanitize_evidence(gate.get("evidenceRefs"))
    derived = Counter(receipt["lifecycle"] for receipt in feed["receipts"])
    expected = {
        "setupReserved": derived["setup-reserved"],
        "active": derived["active"],
        "waiting": derived["waiting"],
        "ownerGated": derived["owner-gated"],
        "failed": derived["failed"],
        "done": derived["done"],
        "acknowledged": derived["acknowledged"],
        "runnable": (
            None
            if any(receipt["runnable"] is None for receipt in feed["receipts"])
            else sum(receipt["runnable"] is True for receipt in feed["receipts"])
        ),
        "quarantined": len(feed["quarantine"]),
    }
    if any(feed["counts"].get(key) != value for key, value in expected.items()):
        fail("FEED_INVALID", "feed counts are not receipt-derived")


def ledger_evidence(
    closure: dict[str, Any] | None,
    handback: dict[str, Any] | None,
    capacity: sqlite3.Row | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]], bool]:
    evidence: list[dict[str, str]] = []
    acceptance: list[dict[str, str]] = []
    if handback is not None and handback.get("disposition") != "blocked":
        acceptance.append(
            {
                "kind": "test",
                "ref": "test:handback-accepted",
                "label": "Canonical clean handback accepted",
            }
        )
    if closure:
        for index, item in enumerate(closure.get("checks", [])[:12], start=1):
            result = item.get("result") if isinstance(item, dict) else None
            if result in {"pass", "fail", "pending", "skipped", "unexecuted"}:
                evidence.append(
                    {"kind": "test", "ref": f"test:check-{index}-{result}"}
                )
        exact = closure.get("exact_refs")
        if isinstance(exact, dict):
            for key in ("candidate", "merge", "default"):
                value = exact.get(key)
                if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{40}", value):
                    evidence.append({"kind": "commit", "ref": f"commit:{value}"})
            pull_request = exact.get("pull_request")
            if isinstance(pull_request, str) and re.fullmatch(
                r"(?:pr[-:]?)?[0-9]{1,10}", pull_request, re.IGNORECASE
            ):
                evidence.append(
                    {
                        "kind": "pullRequest",
                        "ref": f"pullRequest:{re.sub(r'\D', '', pull_request)}",
                    }
                )
    terminal_leaf = False
    if capacity is not None and capacity["successor_task_id"] is None:
        outcome = capacity["outcome"]
        decision = {
            "EMPTY": "decision:terminal-leaf",
            "CAPACITY_FULL": "decision:capacity-full",
            "OWNER_GATED": "decision:owner-gated",
        }.get(outcome)
        if decision:
            evidence.append({"kind": "decision", "ref": decision})
            terminal_leaf = True
    combined = sanitize_evidence((evidence + acceptance)[-24:])
    acceptance_count = len(acceptance)
    return (
        combined[:-acceptance_count] if acceptance_count else combined,
        combined[-acceptance_count:] if acceptance_count else [],
        terminal_leaf,
    )


def duration_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    actual = json.loads(row["actual_json"]) if row["actual_json"] else None
    return {
        "estimate_version": row["estimate_version"],
        "estimated_bucket": row["estimated_bucket"],
        "current_lane": row["current_lane"],
        "expected_components": {
            "setup_seconds": row["expected_setup_seconds"],
            "test_seconds": row["expected_test_seconds"],
            "remote_wait_seconds": row["expected_external_wait_seconds"],
        },
        "actual": actual,
    }


def owner_gate_projection(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        if row["route"] == "OWNER_GATE" and row["gate_fingerprint"]:
            grouped[row["gate_fingerprint"]].append(row)
    output = []
    for gate_fingerprint, group in grouped.items():
        latest = max(group, key=lambda row: (row["recorded_at"], row["request_id"]))
        decision_code = latest["reason_code"]
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", decision_code):
            fail("PRIVACY_REJECTED", "owner gate decision code is unsafe")
        digest = hashlib.sha256(
            canonical(["dashboard-receipt-feed/1.0", "owner-gate", gate_fingerprint]).encode(
                "ascii"
            )
        ).hexdigest()
        output.append(
            {
                "fingerprint": f"rcpt_{digest}",
                "revision": len(group),
                "decisionCode": decision_code,
                "recordedAt": latest["recorded_at"],
                "nextSafeMove": "review-owner-gate",
                "evidenceRefs": [
                    {
                        "kind": "decision",
                        "ref": f"decision:{decision_code.lower()}",
                    }
                ],
            }
        )
    return sorted(output, key=lambda item: item["fingerprint"])


def state_database(state_dir: str) -> Path:
    state = Path(state_dir).absolute()
    database = state / "orchestrator.sqlite3"
    if state.is_symlink() or database.is_symlink() or not database.is_file():
        fail("STATE_UNSAFE", "state database must be a regular non-symlink file")
    return database


def feed_from_ledger(
    state_dir: str,
    *,
    generated_at: str,
    served_at: str,
    freshness_threshold_seconds: int,
) -> dict[str, Any]:
    if parse_time(generated_at) is None or parse_time(served_at) is None:
        fail("INPUT_INVALID", "generatedAt and servedAt must be RFC3339 timestamps")
    database = state_database(state_dir)
    try:
        connection = sqlite3.connect(
            f"file:{database}?mode=ro",
            uri=True,
            timeout=0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            fail("STATE_CORRUPT", "ledger quick_check failed")
        connection.execute("BEGIN")
        metadata = {
            row["key"]: row["value"]
            for row in connection.execute("SELECT key,value FROM metadata")
        }
        if metadata.get("schema_version") != FIRESTARTER_SCHEMA:
            fail("VERSION_UNSUPPORTED", "ledger schema must be 1.2")
        task_rows = list(
            connection.execute(
                "SELECT * FROM tasks ORDER BY priority DESC,created_at,task_id"
            )
        )
        timing_by_task = {
            row["task_id"]: row for row in connection.execute("SELECT * FROM task_timing")
        }
        handbacks_by_task: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in connection.execute(
            "SELECT * FROM handbacks ORDER BY recorded_at,handback_id"
        ):
            handbacks_by_task[row["task_id"]].append(row)
        capacity_by_task = {
            row["task_id"]: row
            for row in connection.execute("SELECT * FROM capacity_sagas")
        }
        launch_by_task = {
            row["task_id"]: row
            for row in connection.execute("SELECT * FROM launches")
        }
        decisions = list(connection.execute("SELECT * FROM decisions"))
        configured_values = {
            row["configured_capacity"] for row in capacity_by_task.values()
        }
        if len(configured_values) > 1:
            fail("CAPACITY_CONFLICT", "ledger capacity rows disagree")
        active_count = 0
        reserved_count = 0
        status_tasks: list[dict[str, Any]] = []
        task_facts: list[dict[str, Any]] = []
        mirrored: list[dict[str, Any]] = []
        generated = parse_time(generated_at)
        assert generated is not None
        for row in task_rows:
            identity = {
                "sourceEventKey": row["source_event_key"],
                "outcomeKey": row["outcome_key"],
                "receiptKind": "task",
                "canonicalOwnerKey": "ledger-owner",
            }
            safe_identity = sanitized_identity(identity)
            if row["state"] in {"DUPLICATE_STOP", "SUPERSEDED"}:
                mirrored.append(
                    {
                        "fingerprint": fingerprint_of(safe_identity),
                        "reason": "mirror",
                        "mirrorOf": None,
                        "excludedFromCounts": True,
                    }
                )
                continue
            launch = launch_by_task.get(row["task_id"])
            receipt = (
                json.loads(launch["receipt_json"])
                if launch is not None and launch["receipt_json"]
                else None
            )
            if row["state"] == "RUNNING" and receipt is None:
                fail("RECEIPT_REQUIRED", "RUNNING ledger task lacks launch receipt")
            if row["state"] == "RUNNING":
                active_count += 1
            elif row["state"] == "LAUNCH_PENDING":
                reserved_count += 1
            claim = connection.execute(
                """SELECT expires_at FROM owner_claims
                   WHERE task_id=? AND status='active'""",
                (row["task_id"],),
            ).fetchone()
            stale = (
                None
                if claim is None
                else parse_time(claim["expires_at"]) <= generated
            )
            block = json.loads(row["block_json"]) if row["block_json"] else None
            closure = json.loads(row["closure_json"]) if row["closure_json"] else None
            handback_row = (
                handbacks_by_task[row["task_id"]][-1]
                if handbacks_by_task[row["task_id"]]
                else None
            )
            handback = (
                json.loads(handback_row["body_json"]) if handback_row is not None else None
            )
            capacity = capacity_by_task.get(row["task_id"])
            evidence, acceptance, terminal_leaf = ledger_evidence(
                closure, handback, capacity
            )
            successors = (
                [capacity["successor_task_id"]]
                if capacity is not None and capacity["successor_task_id"]
                else []
            )
            gate_kind = None
            if isinstance(block, dict):
                if block.get("classification") == "owner_gate":
                    gate_kind = "owner"
                elif block.get("classification") == "external_dependency":
                    gate_kind = "external"
                elif block.get("classification") == "dependency":
                    gate_kind = "dependency"
            status_tasks.append(
                {
                    "task_id": row["task_id"],
                    "state": row["state"],
                    "canonical_external_thread_id": (
                        receipt.get("external_thread_id") if receipt else None
                    ),
                    "block": block,
                    "duration": duration_from_row(timing_by_task.get(row["task_id"])),
                    "freshness": {"stale": stale},
                }
            )
            fact: dict[str, Any] = {
                "taskKey": row["task_id"],
                "identity": safe_identity,
                "revision": max(1, row["fencing_token"]),
                "dependsOnTaskKeys": json.loads(row["dependencies_json"]),
                "successorTaskKeys": successors,
                "terminalLeaf": terminal_leaf,
                "evidence": evidence,
                "acceptanceEvidence": acceptance,
            }
            if gate_kind is not None:
                fact["gateKind"] = gate_kind
            task_facts.append(fact)
        capacity_rows = [
            {
                "configured_capacity": row["configured_capacity"],
                "active_count": active_count,
                "reserved_setup_count": reserved_count,
                "failure_state": (
                    "CAPACITY_INVARIANT_FAILED"
                    if row["runnable_queue_count"] > 0
                    and active_count + reserved_count != row["configured_capacity"]
                    else None
                ),
            }
            for row in capacity_by_task.values()
        ]
        status_response = {
            "interface_version": INTERFACE_VERSION,
            "ok": True,
            "operation": "status",
            "result": {
                "schema_version": FIRESTARTER_SCHEMA,
                "revision": int(metadata.get("revision", "0")),
                "tasks": status_tasks,
                "capacity": capacity_rows,
                "capacity_failure": any(
                    item["failure_state"] is not None for item in capacity_rows
                ),
                "duration": {
                    "root_excluded_from_worker_capacity": True,
                    "receipt_backed_lane_counts": {"all": active_count},
                    "reserved_setup_lane_counts": {"all": reserved_count},
                    "freshness": {"evaluated_at": generated_at},
                },
            },
        }
        feed = export_feed(
            {
                "interfaceVersion": INTERFACE_VERSION,
                "servedAt": served_at,
                "freshnessThresholdSeconds": freshness_threshold_seconds,
                "status": status_response,
                "taskFacts": task_facts,
            }
        )
        if mirrored:
            feed["quarantine"].extend(mirrored)
            feed["counts"]["quarantined"] = len(feed["quarantine"])
            feed["source"]["discrepancies"] = sorted(
                set(feed["source"]["discrepancies"]) | {"MIRROR_QUARANTINED"}
            )
            feed["source"]["sourceStatus"] = "degraded"
        feed["ownerGates"] = owner_gate_projection(decisions)
        validate_feed(feed)
        connection.rollback()
        return feed
    except sqlite3.Error as error:
        raise ExportError("STATE_UNAVAILABLE", "ledger read failed closed") from error
    finally:
        if "connection" in locals():
            connection.close()


def safe_output_dir(raw: str) -> Path:
    output = Path(raw).absolute()
    if output.exists():
        if output.is_symlink() or not output.is_dir():
            fail("OUTPUT_UNSAFE", "output must be a non-symlink directory")
    else:
        output.mkdir(parents=True, mode=0o700)
    return output


def atomic_write(path: Path, payload: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".receipt-feed-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def pointer_payload(feed: dict[str, Any], digest: str, snapshot: str) -> bytes:
    return (
        canonical(
            {
                "schemaVersion": FEED_VERSION,
                "sha256": digest,
                "snapshot": snapshot,
                "generatedAt": feed["source"]["generatedAt"],
            }
        )
        + "\n"
    ).encode("utf-8")


def validated_pointer(output: Path, name: str) -> tuple[dict[str, Any], bytes] | None:
    pointer = output / name
    if not pointer.exists():
        return None
    if pointer.is_symlink() or not pointer.is_file():
        fail("LKG_INVALID", f"{name} is unsafe")
    payload = pointer.read_bytes()
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ExportError("LKG_INVALID", f"{name} is invalid") from error
    if set(value) != {"schemaVersion", "sha256", "snapshot", "generatedAt"}:
        fail("LKG_INVALID", f"{name} has invalid fields")
    if value["schemaVersion"] != FEED_VERSION or not re.fullmatch(
        r"[a-f0-9]{64}", value["sha256"]
    ):
        fail("LKG_INVALID", f"{name} has invalid identity")
    snapshot = output / value["snapshot"]
    if (
        snapshot.parent != output
        or snapshot.is_symlink()
        or not snapshot.is_file()
        or hashlib.sha256(snapshot.read_bytes()).hexdigest() != value["sha256"]
    ):
        fail("LKG_INVALID", f"{name} snapshot failed content verification")
    validate_feed(json.loads(snapshot.read_text(encoding="utf-8")))
    return value, payload


def publish_ledger(
    state_dir: str,
    output_dir: str,
    *,
    generated_at: str,
    served_at: str,
    freshness_threshold_seconds: int,
) -> dict[str, Any]:
    feed = feed_from_ledger(
        state_dir,
        generated_at=generated_at,
        served_at=served_at,
        freshness_threshold_seconds=freshness_threshold_seconds,
    )
    validate_feed(feed)
    output = safe_output_dir(output_dir)
    snapshot_bytes = (canonical(feed) + "\n").encode("utf-8")
    digest = hashlib.sha256(snapshot_bytes).hexdigest()
    snapshot_name = f"{SNAPSHOT_PREFIX}{digest}.json"
    snapshot = output / snapshot_name
    if snapshot.exists():
        if snapshot.is_symlink() or snapshot.read_bytes() != snapshot_bytes:
            fail("SNAPSHOT_CONFLICT", "content-addressed snapshot conflicts")
    else:
        atomic_write(snapshot, snapshot_bytes)
    current = validated_pointer(output, CURRENT_POINTER)
    new_pointer = pointer_payload(feed, digest, snapshot_name)
    if current is not None and current[1] != new_pointer:
        atomic_write(output / PREVIOUS_POINTER, current[1])
    atomic_write(output / CURRENT_POINTER, new_pointer)
    return {
        "schemaVersion": FEED_VERSION,
        "sha256": digest,
        "snapshot": snapshot_name,
        "currentPointer": CURRENT_POINTER,
        "previousPointer": (
            PREVIOUS_POINTER if (output / PREVIOUS_POINTER).exists() else None
        ),
        "sourceStatus": feed["source"]["sourceStatus"],
        "freshness": feed["source"]["freshness"],
    }


def validate_snapshot(path: str) -> dict[str, Any]:
    snapshot = Path(path).absolute()
    if snapshot.is_symlink() or not snapshot.is_file():
        fail("INPUT_UNSAFE", "snapshot must be a regular non-symlink file")
    payload = snapshot.read_bytes()
    if len(payload) > MAX_JSON_BYTES:
        fail("INPUT_TOO_LARGE", "snapshot exceeds one megabyte")
    try:
        feed = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ExportError("JSON_INVALID", "snapshot is invalid JSON") from error
    validate_feed(feed)
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "schemaVersion": FEED_VERSION,
        "sha256": digest,
        "sourceStatus": feed["source"]["sourceStatus"],
        "freshness": feed["source"]["freshness"],
    }


def rollback_pointer(output_dir: str) -> dict[str, Any]:
    output = safe_output_dir(output_dir)
    current = validated_pointer(output, CURRENT_POINTER)
    previous = validated_pointer(output, PREVIOUS_POINTER)
    if previous is None:
        fail("LKG_UNAVAILABLE", "no previous last-known-good snapshot exists")
    atomic_write(output / CURRENT_POINTER, previous[1])
    if current is not None:
        atomic_write(output / PREVIOUS_POINTER, current[1])
    return {
        "schemaVersion": FEED_VERSION,
        "sha256": previous[0]["sha256"],
        "snapshot": previous[0]["snapshot"],
        "currentPointer": CURRENT_POINTER,
        "rollbackApplied": True,
    }


def duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("JSON_INVALID", "JSON contains duplicate keys")
        result[key] = value
    return result


def read_request(path: str) -> Any:
    if path == "-":
        payload = sys.stdin.buffer.read(MAX_JSON_BYTES + 1)
    else:
        source = Path(path)
        if source.is_symlink() or not source.is_file():
            fail("INPUT_UNSAFE", "request must be a regular non-symlink file")
        if source.stat().st_size > MAX_JSON_BYTES:
            fail("INPUT_TOO_LARGE", "request exceeds one megabyte")
        payload = source.read_bytes()
    if len(payload) > MAX_JSON_BYTES:
        fail("INPUT_TOO_LARGE", "request exceeds one megabyte")
    try:
        return json.loads(payload, object_pairs_hook=duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExportError("JSON_INVALID", "request must be valid UTF-8 JSON") from error


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sanitized one-way receipt-feed exporter and validator"
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="adapt-status",
        choices=[
            "adapt-status",
            "publish-ledger",
            "validate-snapshot",
            "rollback",
        ],
    )
    parser.add_argument("--request", default="-")
    parser.add_argument("--state-dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--snapshot")
    parser.add_argument("--generated-at")
    parser.add_argument("--served-at")
    parser.add_argument("--stale-threshold-seconds", type=int, default=60)
    arguments = parser.parse_args()
    try:
        if arguments.command == "adapt-status":
            result = export_feed(read_request(arguments.request))
        elif arguments.command == "publish-ledger":
            if not all(
                (
                    arguments.state_dir,
                    arguments.output_dir,
                    arguments.generated_at,
                    arguments.served_at,
                )
            ):
                fail(
                    "INPUT_INVALID",
                    "publish-ledger requires state/output directories and timestamps",
                )
            if arguments.stale_threshold_seconds < 1:
                fail("INPUT_INVALID", "stale threshold must be positive")
            result = publish_ledger(
                arguments.state_dir,
                arguments.output_dir,
                generated_at=arguments.generated_at,
                served_at=arguments.served_at,
                freshness_threshold_seconds=arguments.stale_threshold_seconds,
            )
        elif arguments.command == "validate-snapshot":
            if not arguments.snapshot:
                fail("INPUT_INVALID", "validate-snapshot requires --snapshot")
            result = validate_snapshot(arguments.snapshot)
        else:
            if not arguments.output_dir:
                fail("INPUT_INVALID", "rollback requires --output-dir")
            result = rollback_pointer(arguments.output_dir)
        print(canonical(result))
        return 0
    except ExportError as error:
        print(
            canonical(
                {
                    "ok": False,
                    "error": {"code": error.code, "message": error.message},
                }
            ),
            file=sys.stderr,
        )
        return 2
    except Exception:
        print(
            canonical(
                {
                    "ok": False,
                    "error": {
                        "code": "EXPORT_FAILED",
                        "message": "receipt feed export failed closed",
                    },
                }
            ),
            file=sys.stderr,
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
