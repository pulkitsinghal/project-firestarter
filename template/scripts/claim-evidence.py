#!/usr/bin/env python3
"""Pure, offline claim gate. Caller must verify evidence; no content is echoed."""
from __future__ import annotations

import json
import math
import sys

KINDS = {"observation", "absence", "provenance", "worker_active", "appointment"}
CLASSES = {"primary", "reported", "inferred", "synthetic"}
RESULTS = {"supports", "contradicts", "not_found", "unavailable"}


def validate(payload: object) -> dict:
    """Return an allow/qualify/block decision, not a truth certification.

    Source IDs, scope inventory, and evidence authenticity are trusted adapter
    inputs. A caller cannot turn this into evidence by asserting verified=true.
    """
    def invalid():
        return {"decision": "block", "codes": ["INVALID_INPUT"]}

    if not isinstance(payload, dict) or set(payload) != {
        "kind", "now", "max_age_seconds", "required_scopes", "evidence"
    }:
        return invalid()
    kind = payload["kind"]
    now, age = payload["now"], payload["max_age_seconds"]
    def number(value):
        return type(value) in (int, float) and -1e15 <= value <= 1e15 and math.isfinite(value)
    def token(value):
        return isinstance(value, str) and bool(value.strip())
    scopes, evidence = payload["required_scopes"], payload["evidence"]
    if (not isinstance(kind, str) or kind not in KINDS or not number(now)
            or now < 0 or not number(age) or not 0 < age <= 86400
            or not isinstance(scopes, list) or not scopes
            or not all(token(s) for s in scopes) or len(set(scopes)) != len(scopes)
            or not isinstance(evidence, list) or len(evidence) > 1000):
        return invalid()
    ids = set()
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {
            "id", "scope", "source_class", "reference", "observed_at",
            "result", "coverage_complete", "state"
        }:
            return invalid()
        if (not all(token(item[k]) for k in ("id", "scope", "reference"))
                or item["id"] in ids or item["scope"] not in scopes
                or not isinstance(item["source_class"], str)
                or item["source_class"] not in CLASSES
                or not isinstance(item["result"], str) or item["result"] not in RESULTS
                or type(item["coverage_complete"]) is not bool
                or not number(item["observed_at"]) or item["observed_at"] < 0
                or item["state"] not in (None, "active", "idle", "scheduled", "confirmed", "cancelled")):
            return invalid()
        ids.add(item["id"])
    codes = set()
    fresh = []
    for item in evidence:
        elapsed = now - item["observed_at"]
        if elapsed < 0:
            codes.add("FUTURE_EVIDENCE")
        elif elapsed > age:
            codes.add("STALE_EVIDENCE")
        else:
            fresh.append(item)
    if any(e["result"] == "contradicts" for e in evidence):
        codes.add("CONFLICTING_EVIDENCE")
    if any(e["result"] == "unavailable" for e in evidence):
        codes.add("UNAVAILABLE_SOURCE")
    if any(not e["coverage_complete"] for e in evidence):
        codes.add("PARTIAL_SOURCE")
    covered = {e["scope"] for e in fresh
               if e["source_class"] == "primary" and e["coverage_complete"]
               and e["result"] != "unavailable"}
    if covered != set(scopes):
        codes.add("INCOMPLETE_COVERAGE")
    supporting = [e for e in fresh if e["result"] == "supports"]
    primary = [e for e in supporting if e["source_class"] == "primary"]
    if kind == "absence":
        if supporting:
            codes.add("POSITIVE_FINDING_PREVENTS_ABSENCE")
        if any(e["source_class"] != "primary" for e in evidence):
            codes.add("NONPRIMARY_ABSENCE_EVIDENCE")
        if not evidence:
            codes.add("NO_EVIDENCE")
    else:
        if not primary:
            codes.add("NO_PRIMARY_SUPPORT")
        if any(e["source_class"] == "synthetic" for e in supporting):
            codes.add("SYNTHETIC_NOT_PROVENANCE")
    if kind == "worker_active":
        if not any(e["state"] == "active" for e in primary):
            codes.add("NO_ACTIVE_WORKER_RECEIPT")
        if any(e["state"] not in (None, "active") for e in fresh) or any(
                e["state"] is None for e in supporting):
            codes.add("CONFLICTING_WORKER_STATE")
    if kind == "appointment":
        # Both sources must be included even if only one has the confirmation.
        if not {"calendar", "messages"} <= set(scopes):
            codes.add("APPOINTMENT_SOURCES_MISSING")
        if not any(e["state"] == "confirmed" for e in primary):
            codes.add("NO_APPOINTMENT_CONFIRMATION")
        if any(e["state"] == "cancelled" for e in evidence):
            codes.add("APPOINTMENT_CANCELLED")
    hard = {"CONFLICTING_EVIDENCE", "FUTURE_EVIDENCE", "POSITIVE_FINDING_PREVENTS_ABSENCE",
            "SYNTHETIC_NOT_PROVENANCE", "NO_ACTIVE_WORKER_RECEIPT", "CONFLICTING_WORKER_STATE", "APPOINTMENT_CANCELLED"}
    decision = "block" if codes & hard else "qualify" if codes else "allow"
    return {"decision": decision, "codes": sorted(codes)}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def main():
    try:
        raw = sys.stdin.read(1048577)
        if len(raw) > 1048576:
            raise ValueError("oversize")
        result = validate(json.loads(raw, object_pairs_hook=unique_object))
    except (ValueError, TypeError, RecursionError):
        result = {"decision": "block", "codes": ["INVALID_INPUT"]}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["decision"] == "allow" else 2 if result["codes"] == ["INVALID_INPUT"] else 1


if __name__ == "__main__":
    sys.exit(main())
