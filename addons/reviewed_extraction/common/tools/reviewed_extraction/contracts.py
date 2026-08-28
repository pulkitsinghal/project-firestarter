"""Closed, content-minimized types for human-reviewed structured extraction.

Raw source documents, page text, note bodies, transcripts, and private records
are deliberately absent from these types. A claim references its source only by
an opaque source ID, a `sha256:` content digest, and integer character offsets.
The extracted *value* a human confirmed is a bounded opaque token; the raw span
it was drawn from stays caller-side and is never persisted into a claim, a
reduced decision, or an egress payload.

Requirements are derived independently from Firestarter/Auggie review needs and
neutral public standards: W3C PROV provenance (source + actor attribution),
JSON Schema 2020-12 (closed, enum-locked contracts), and the data-minimization
and purpose-limitation principles common to general privacy guidance.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from enum import Enum
import hashlib
import json
import re
from typing import Optional, Tuple


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
SAFE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_FIELD_PATH = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}(?:\.[A-Za-z0-9][A-Za-z0-9_-]{0,63}){0,15}$"
)
VALUE_MAX_LENGTH = 256
OFFSET_MAX = 2 ** 31
SUPERSEDES_MAX = 16


def require_id(value: str, field: str) -> None:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError(f"{field} must be an opaque identifier")


def require_field_path(value: str, field: str) -> None:
    if not isinstance(value, str) or not SAFE_FIELD_PATH.fullmatch(value):
        raise ValueError(f"{field} must be an opaque dotted field path")


def require_value(value: str, field: str) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= VALUE_MAX_LENGTH:
        raise ValueError(f"{field} must be a bounded non-empty token")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ValueError(f"{field} must not contain control characters")


def require_digest(value: str, field: str) -> None:
    if not isinstance(value, str) or not SAFE_DIGEST.fullmatch(value):
        raise ValueError(f"{field} must be a sha256 digest")


def canonical_digest(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class ClaimState(str, Enum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    UNKNOWN = "unknown"
    OMITTED = "omitted"
    CONFLICTED = "conflicted"
    SUPERSEDED = "superseded"


RELEASABLE_STATES = frozenset({ClaimState.CONFIRMED, ClaimState.CORRECTED})
STATE_PRECEDENCE = {ClaimState.CORRECTED: 2, ClaimState.CONFIRMED: 1}


class Purpose(str, Enum):
    TREATMENT = "treatment"
    PAYMENT = "payment"
    OPERATIONS = "operations"
    RESEARCH = "research"
    PATIENT_ACCESS = "patient-access"


class ReductionCode(str, Enum):
    RELEASABLE_CONFIRMED = "releasable-confirmed"
    RELEASABLE_CORRECTED = "releasable-corrected"
    WITHHELD_PROPOSED = "withheld-proposed"
    WITHHELD_UNKNOWN = "withheld-unknown"
    WITHHELD_OMITTED = "withheld-omitted"
    WITHHELD_CONFLICTED = "withheld-conflicted"
    WITHHELD_SUPERSEDED = "withheld-superseded"


RELEASABLE_OUTCOMES = frozenset(
    {ReductionCode.RELEASABLE_CONFIRMED, ReductionCode.RELEASABLE_CORRECTED}
)


class EgressCode(str, Enum):
    RELEASED = "released"
    DROPPED_NO_DECISION = "dropped-no-decision"
    DROPPED_NOT_RELEASABLE = "dropped-not-releasable"
    DROPPED_PURPOSE_MISMATCH = "dropped-purpose-mismatch"
    DROPPED_RECIPIENT_MISMATCH = "dropped-recipient-mismatch"


class EvidenceCode(str, Enum):
    VERIFIED = "verified"
    DIGEST_MISMATCH = "digest-mismatch"
    OFFSET_OUT_OF_RANGE = "offset-out-of-range"


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """A content-free pointer into a private source: digest plus offsets only."""

    source_id: str
    source_digest: str
    start_offset: int
    end_offset: int

    def __post_init__(self) -> None:
        require_id(self.source_id, "source_id")
        require_digest(self.source_digest, "source_digest")
        if not isinstance(self.start_offset, int) or isinstance(self.start_offset, bool):
            raise ValueError("start_offset must be an integer")
        if not isinstance(self.end_offset, int) or isinstance(self.end_offset, bool):
            raise ValueError("end_offset must be an integer")
        if self.start_offset < 0 or self.end_offset < 0:
            raise ValueError("evidence offsets must be non-negative")
        if self.start_offset > self.end_offset:
            raise ValueError("evidence start offset must not exceed end offset")
        if self.end_offset > OFFSET_MAX:
            raise ValueError("evidence offsets exceed the policy bound")

    def to_contract_dict(self) -> dict:
        return {
            "sourceId": self.source_id,
            "sourceDigest": self.source_digest,
            "startOffset": self.start_offset,
            "endOffset": self.end_offset,
        }


@dataclass(frozen=True, slots=True)
class ExtractionClaim:
    """One human-reviewed proposal about a single opaque field path.

    The `value` is the structured value a reviewer confirmed or corrected, never
    the raw source span. `evidence` locates the span by digest and offsets so a
    verifier can check provenance without the claim ever holding source content.
    """

    claim_id: str
    field_path: str
    value: str
    state: ClaimState
    actor_id: str
    purpose: Purpose
    recipient_id: str
    evidence: EvidenceRef
    sequence: int
    supersedes: Tuple[str, ...] = dataclass_field(default=())

    def __post_init__(self) -> None:
        require_id(self.claim_id, "claim_id")
        require_field_path(self.field_path, "field_path")
        require_value(self.value, "value")
        if not isinstance(self.state, ClaimState):
            raise ValueError("state must be a ClaimState")
        require_id(self.actor_id, "actor_id")
        if not isinstance(self.purpose, Purpose):
            raise ValueError("purpose must be a Purpose")
        require_id(self.recipient_id, "recipient_id")
        if not isinstance(self.evidence, EvidenceRef):
            raise ValueError("evidence must be an EvidenceRef")
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool):
            raise ValueError("sequence must be an integer")
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if len(self.supersedes) > SUPERSEDES_MAX:
            raise ValueError("supersedes set exceeds the policy bound")
        if len(set(self.supersedes)) != len(self.supersedes):
            raise ValueError("supersedes set must be unique")
        for superseded_id in self.supersedes:
            require_id(superseded_id, "supersedes")
            if superseded_id == self.claim_id:
                raise ValueError("a claim cannot supersede itself")

    def to_contract_dict(self) -> dict:
        return {
            "schemaVersion": "1.0",
            "claimId": self.claim_id,
            "fieldPath": self.field_path,
            "value": self.value,
            "state": self.state.value,
            "actorId": self.actor_id,
            "purpose": self.purpose.value,
            "recipientId": self.recipient_id,
            "evidence": self.evidence.to_contract_dict(),
            "sequence": self.sequence,
            "supersedes": list(self.supersedes),
        }

    @classmethod
    def from_contract_dict(cls, value: dict) -> "ExtractionClaim":
        expected = {
            "schemaVersion",
            "claimId",
            "fieldPath",
            "value",
            "state",
            "actorId",
            "purpose",
            "recipientId",
            "evidence",
            "sequence",
            "supersedes",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("extraction claim fields do not match schema 1.0")
        if value["schemaVersion"] != "1.0":
            raise ValueError("unsupported extraction claim schema")
        evidence_value = value["evidence"]
        evidence_keys = {"sourceId", "sourceDigest", "startOffset", "endOffset"}
        if not isinstance(evidence_value, dict) or set(evidence_value) != evidence_keys:
            raise ValueError("evidence fields do not match schema 1.0")
        evidence = EvidenceRef(
            source_id=evidence_value["sourceId"],
            source_digest=evidence_value["sourceDigest"],
            start_offset=evidence_value["startOffset"],
            end_offset=evidence_value["endOffset"],
        )
        return cls(
            claim_id=value["claimId"],
            field_path=value["fieldPath"],
            value=value["value"],
            state=ClaimState(value["state"]),
            actor_id=value["actorId"],
            purpose=Purpose(value["purpose"]),
            recipient_id=value["recipientId"],
            evidence=evidence,
            sequence=value["sequence"],
            supersedes=tuple(value["supersedes"]),
        )


@dataclass(frozen=True, slots=True)
class ReducedDecision:
    """The deterministic fold of every claim for one field path."""

    field_path: str
    outcome: ReductionCode
    released_value: Optional[str]
    winning_claim_id: Optional[str]
    actor_id: Optional[str]
    purpose: Optional[Purpose]
    recipient_id: Optional[str]
    evidence: Optional[EvidenceRef]
    contributing_claim_ids: Tuple[str, ...]
    superseded_claim_ids: Tuple[str, ...]

    def __post_init__(self) -> None:
        require_field_path(self.field_path, "field_path")
        if not isinstance(self.outcome, ReductionCode):
            raise ValueError("outcome must be a ReductionCode")
        releasable = self.outcome in RELEASABLE_OUTCOMES
        has_value = self.released_value is not None
        if releasable != has_value:
            raise ValueError("released_value must be present exactly when releasable")
        if releasable:
            require_value(self.released_value, "released_value")
            require_id(self.winning_claim_id, "winning_claim_id")
            require_id(self.actor_id, "actor_id")
            require_id(self.recipient_id, "recipient_id")
            if not isinstance(self.purpose, Purpose):
                raise ValueError("releasable decision must carry a purpose")
            if not isinstance(self.evidence, EvidenceRef):
                raise ValueError("releasable decision must carry evidence")
        else:
            if self.winning_claim_id is not None:
                raise ValueError("withheld decision must not name a winning claim")
            if (
                self.released_value is not None
                or self.actor_id is not None
                or self.purpose is not None
                or self.recipient_id is not None
                or self.evidence is not None
            ):
                raise ValueError("withheld decision must carry no released fields")

    @property
    def is_releasable(self) -> bool:
        return self.outcome in RELEASABLE_OUTCOMES

    @property
    def decision_state(self) -> Optional[str]:
        if self.outcome is ReductionCode.RELEASABLE_CONFIRMED:
            return ClaimState.CONFIRMED.value
        if self.outcome is ReductionCode.RELEASABLE_CORRECTED:
            return ClaimState.CORRECTED.value
        return None

    def to_contract_dict(self) -> dict:
        return {
            "schemaVersion": "1.0",
            "fieldPath": self.field_path,
            "outcome": self.outcome.value,
            "releasedValue": self.released_value,
            "winningClaimId": self.winning_claim_id,
            "actorId": self.actor_id,
            "purpose": self.purpose.value if self.purpose is not None else None,
            "recipientId": self.recipient_id,
            "sourceId": self.evidence.source_id if self.evidence is not None else None,
            "sourceDigest": (
                self.evidence.source_digest if self.evidence is not None else None
            ),
            "contributingClaimIds": sorted(self.contributing_claim_ids),
            "supersededClaimIds": sorted(self.superseded_claim_ids),
        }
