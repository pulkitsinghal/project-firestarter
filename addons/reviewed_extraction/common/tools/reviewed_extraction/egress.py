"""Allowlisted egress builder.

The egress payload is assembled entirely by this pure code from
:class:`ReducedDecision` objects and an explicit request. A field leaves only
when every gate passes, in order:

1. the field path was explicitly requested (non-requested paths are never even
   iterated, so a releasable-but-unrequested field cannot leak);
2. a reduced decision exists for it;
3. that decision is releasable (``confirmed`` / ``corrected`` only);
4. the decision's purpose equals the request's purpose (purpose limitation);
5. the decision's recipient equals the request's recipient.

The released ``value`` is copied from the human-confirmed decision, never from a
model. Anything that fails a gate is dropped and recorded with a reason code:
fail-closed by construction.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping

from .contracts import (
    EgressCode,
    Purpose,
    ReducedDecision,
    RELEASABLE_OUTCOMES,
    canonical_digest,
    require_field_path,
    require_id,
)


CONTRACT_VERSION = "0.1.0"
REQUEST_MAX_FIELDS = 256

RELEASED_FIELD_KEYS = frozenset(
    {"fieldPath", "value", "decisionState", "actorId", "sourceId", "sourceDigest"}
)
FORBIDDEN_KEY_PARTS = (
    "text",
    "raw",
    "content",
    "snippet",
    "page",
    "body",
    "bytes",
    "offset",
    "span",
    "ocr",
    "screenshot",
    "cookie",
    "token",
    "credential",
    "password",
)


def classify(
    field_path: str,
    decision: ReducedDecision | None,
    *,
    purpose: Purpose,
    recipient_id: str,
) -> EgressCode:
    """Return the egress disposition for one requested field path."""

    if decision is None:
        return EgressCode.DROPPED_NO_DECISION
    if decision.outcome not in RELEASABLE_OUTCOMES:
        return EgressCode.DROPPED_NOT_RELEASABLE
    if decision.purpose is not purpose:
        return EgressCode.DROPPED_PURPOSE_MISMATCH
    if decision.recipient_id != recipient_id:
        return EgressCode.DROPPED_RECIPIENT_MISMATCH
    return EgressCode.RELEASED


def build_egress(
    requested_field_paths: Iterable[str],
    reductions: Mapping[str, ReducedDecision],
    *,
    purpose: Purpose,
    recipient_id: str,
) -> Dict[str, Any]:
    """Build the allowlisted egress payload (confirmed/corrected ∩ requested)."""

    if not isinstance(purpose, Purpose):
        raise ValueError("purpose must be a Purpose")
    require_id(recipient_id, "recipient_id")

    requested = sorted(set(requested_field_paths))
    if len(requested) > REQUEST_MAX_FIELDS:
        raise ValueError("requested field set exceeds the policy bound")
    for field_path in requested:
        require_field_path(field_path, "requested field path")

    released_fields = []
    dropped = []
    for field_path in requested:
        decision = reductions.get(field_path)
        code = classify(
            field_path, decision, purpose=purpose, recipient_id=recipient_id
        )
        if code is EgressCode.RELEASED:
            assert decision is not None  # guaranteed by classify()
            released_fields.append(
                {
                    "fieldPath": field_path,
                    "value": decision.released_value,
                    "decisionState": decision.decision_state,
                    "actorId": decision.actor_id,
                    "sourceId": decision.evidence.source_id,
                    "sourceDigest": decision.evidence.source_digest,
                }
            )
        else:
            dropped.append({"fieldPath": field_path, "code": code.value})

    released_fields.sort(key=lambda item: item["fieldPath"])
    dropped.sort(key=lambda item: item["fieldPath"])
    payload = {
        "schemaVersion": "1.0",
        "contractVersion": CONTRACT_VERSION,
        "purpose": purpose.value,
        "recipientId": recipient_id,
        "fields": released_fields,
        "droppedFieldPaths": dropped,
        "fieldCount": len(released_fields),
        "payloadDigest": canonical_digest(
            {
                "purpose": purpose.value,
                "recipientId": recipient_id,
                "fields": released_fields,
            }
        ),
    }
    assert_minimized_egress(payload)
    return payload


def assert_minimized_egress(payload: Mapping[str, Any]) -> None:
    """Fail closed if the payload carries a raw-content-shaped key."""

    for field in payload["fields"]:
        unknown = set(field) - RELEASED_FIELD_KEYS
        if unknown:
            raise ValueError(f"egress field has unknown keys: {sorted(unknown)}")
        for key in field:
            lowered = key.lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                raise ValueError(f"egress field key is privacy-forbidden: {key}")
    for item in payload["droppedFieldPaths"]:
        if set(item) != {"fieldPath", "code"}:
            raise ValueError("dropped audit entry has unexpected keys")
