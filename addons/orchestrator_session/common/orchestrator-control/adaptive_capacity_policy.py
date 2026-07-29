#!/usr/bin/env python3
"""Deterministic audit-only capacity evaluation.

This module deliberately has no host collector, persistence layer, task
dispatcher, admission hook, or service-control dependency. Callers supply one
closed metrics snapshot and receive an advisory result. The result is never an
authorization or reservation receipt.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from numbers import Real
from pathlib import Path
import re
import sys
from typing import Any


INTERFACE_VERSION = "1.0"
POLICY_VERSION = "0.1.0"
MODE = "audit"
MAX_VISIBLE_CAP = 4
MAX_INPUT_BYTES = 64 * 1024
SOURCE_KINDS = {"synthetic-fixture", "untrusted-local-observation"}
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
EVIDENCE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:-]{0,127}$")
RFC3339_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)


class AuditInputError(ValueError):
    """Closed input-boundary rejection."""


@dataclass(frozen=True)
class Metrics:
    logical_cpus: int
    load_1m: float
    memory_pressure_pct: int
    swap_used_mb: int
    age_seconds: int


@dataclass(frozen=True)
class Capacity:
    visible_cap: int
    internal_sublane_cap: int
    heavy_local_cap: int
    minimum_shipping_slots: int
    conservative: bool
    reason: str


def canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def _strict(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise AuditInputError(f"{label} fields are incompatible")
    return value


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise AuditInputError(f"{label} must be a bounded stable identifier")
    return value


def _timestamp(value: Any, label: str) -> tuple[str, datetime]:
    if not isinstance(value, str) or RFC3339_UTC.fullmatch(value) is None:
        raise AuditInputError(f"{label} must be an RFC3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise AuditInputError(f"{label} must be a valid timestamp") from error
    return value, parsed.astimezone(timezone.utc)


def _integer(value: Any, label: str, low: int, high: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not low <= value <= high
    ):
        raise AuditInputError(f"{label} must be an integer from {low} to {high}")
    return value


def _load(value: Any) -> float:
    if (
        not isinstance(value, Real)
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise AuditInputError("metrics.load_1m must be finite and nonnegative")
    return float(value)


def _source(value: Any) -> dict[str, str]:
    source = _strict(value, {"kind", "evidence_ref"}, "source")
    if source["kind"] not in SOURCE_KINDS:
        raise AuditInputError("source.kind is unsupported")
    evidence_ref = source["evidence_ref"]
    if (
        not isinstance(evidence_ref, str)
        or EVIDENCE_REF.fullmatch(evidence_ref) is None
    ):
        raise AuditInputError("source.evidence_ref must be a coarse local alias")
    return {"kind": source["kind"], "evidence_ref": evidence_ref}


def validate_request(value: Any) -> dict[str, Any]:
    request = _strict(
        value,
        {
            "interface_version",
            "request_id",
            "snapshot_id",
            "source",
            "metrics",
            "visible_limit",
            "now",
        },
        "adaptive capacity request",
    )
    if request["interface_version"] != INTERFACE_VERSION:
        raise AuditInputError("interface_version is unsupported")
    metrics = _strict(
        request["metrics"],
        {
            "logical_cpus",
            "load_1m",
            "memory_pressure_pct",
            "swap_used_mb",
            "observed_at",
        },
        "metrics",
    )
    observed_at, observed = _timestamp(
        metrics["observed_at"], "metrics.observed_at"
    )
    now, evaluated = _timestamp(request["now"], "now")
    age = (evaluated - observed).total_seconds()
    if age < 0:
        raise AuditInputError("metrics.observed_at cannot be in the future")
    return {
        "interface_version": INTERFACE_VERSION,
        "request_id": _identifier(request["request_id"], "request_id"),
        "snapshot_id": _identifier(request["snapshot_id"], "snapshot_id"),
        "source": _source(request["source"]),
        "metrics": {
            "logical_cpus": _integer(
                metrics["logical_cpus"], "metrics.logical_cpus", 1, 1024
            ),
            "load_1m": _load(metrics["load_1m"]),
            "memory_pressure_pct": _integer(
                metrics["memory_pressure_pct"],
                "metrics.memory_pressure_pct",
                0,
                100,
            ),
            "swap_used_mb": _integer(
                metrics["swap_used_mb"],
                "metrics.swap_used_mb",
                0,
                2_147_483_647,
            ),
            "observed_at": observed_at,
        },
        "visible_limit": _integer(
            request["visible_limit"], "visible_limit", 1, MAX_VISIBLE_CAP
        ),
        "now": now,
        "age_seconds": math.ceil(age),
    }


def compute_capacity(metrics: Metrics, visible_limit: int) -> Capacity:
    """Return a bounded advisory capacity for one already-validated snapshot."""

    stale = metrics.age_seconds > 60
    load_ratio = metrics.load_1m / metrics.logical_cpus
    memory_risk = metrics.memory_pressure_pct >= 80 or metrics.swap_used_mb > 0
    high_load = load_ratio >= 1.0
    cap = min(visible_limit, MAX_VISIBLE_CAP)

    if stale:
        return Capacity(min(2, cap), 1, 0, min(1, cap), True, "stale metrics")
    if memory_risk:
        return Capacity(
            min(2, cap), 1, 0, min(1, cap), True, "memory or swap pressure"
        )
    if high_load:
        return Capacity(
            cap, 1, 1, min(2, cap), True, "high load; serialize heavy work"
        )
    return Capacity(cap, 2, 1, min(2, cap), False, "healthy local headroom")


def evaluate(value: Any) -> dict[str, Any]:
    request = validate_request(value)
    metrics = Metrics(
        logical_cpus=request["metrics"]["logical_cpus"],
        load_1m=request["metrics"]["load_1m"],
        memory_pressure_pct=request["metrics"]["memory_pressure_pct"],
        swap_used_mb=request["metrics"]["swap_used_mb"],
        age_seconds=request["age_seconds"],
    )
    capacity = compute_capacity(metrics, request["visible_limit"])
    snapshot_payload = {
        "snapshot_id": request["snapshot_id"],
        "source": request["source"],
        "metrics": request["metrics"],
    }
    snapshot_digest = hashlib.sha256(
        canonical(snapshot_payload).encode("ascii")
    ).hexdigest()
    return {
        "interface_version": INTERFACE_VERSION,
        "ok": True,
        "operation": "evaluate-capacity-snapshot",
        "result": {
            "request_id": request["request_id"],
            "snapshot_id": request["snapshot_id"],
            "snapshot_digest": snapshot_digest,
            "observed_at": request["metrics"]["observed_at"],
            "evaluated_at": request["now"],
            "age_seconds": request["age_seconds"],
            **asdict(capacity),
            "policy_version": POLICY_VERSION,
            "mode": MODE,
            "enforcement_applied": False,
            "reservation_created": False,
            "source_authority_verified": False,
            "service_actions_authorized": False,
        },
    }


def _read_request(path: str) -> Any:
    if path == "-":
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    else:
        target = Path(path)
        stat = target.lstat()
        if target.is_symlink() or not target.is_file() or stat.st_nlink != 1:
            raise AuditInputError("request must be a regular single-link file")
        if stat.st_size > MAX_INPUT_BYTES:
            raise AuditInputError("request exceeds the size limit")
        raw = target.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise AuditInputError("request exceeds the size limit")

    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AuditInputError("request contains duplicate object keys")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuditInputError("request must be valid UTF-8 JSON") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, help="JSON path or - for stdin")
    arguments = parser.parse_args(argv)
    try:
        result = evaluate(_read_request(arguments.request))
    except AuditInputError as error:
        message = str(error)
    except OSError:
        message = "request file is unavailable"
    else:
        print(canonical(result))
        return 0
    print(
        canonical(
            {
                "interface_version": INTERFACE_VERSION,
                "ok": False,
                "operation": "evaluate-capacity-snapshot",
                "error": {
                    "code": "AUDIT_INPUT_REJECTED",
                    "message": message,
                },
            }
        ),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
