from __future__ import annotations

import hashlib

from ..contracts import (
    ClaimState,
    EvidenceRef,
    ExtractionClaim,
    Purpose,
)


SOURCE_BYTES = b"synthetic-source-document-body-for-offset-and-digest-checks"


def digest_bytes(source_bytes: bytes = SOURCE_BYTES) -> str:
    return "sha256:" + hashlib.sha256(source_bytes).hexdigest()


def evidence(
    *,
    source_id: str = "source-a",
    source_digest: str | None = None,
    start_offset: int = 0,
    end_offset: int = 12,
) -> EvidenceRef:
    return EvidenceRef(
        source_id=source_id,
        source_digest=source_digest or digest_bytes(),
        start_offset=start_offset,
        end_offset=end_offset,
    )


def claim(
    *,
    claim_id: str = "claim-a",
    field_path: str = "encounter.chief-complaint",
    value: str = "value-token-a",
    state: ClaimState = ClaimState.CONFIRMED,
    actor_id: str = "actor-reviewer-1",
    purpose: Purpose = Purpose.TREATMENT,
    recipient_id: str = "recipient-ehr",
    evidence_ref: EvidenceRef | None = None,
    sequence: int = 0,
    supersedes: tuple[str, ...] = (),
) -> ExtractionClaim:
    return ExtractionClaim(
        claim_id=claim_id,
        field_path=field_path,
        value=value,
        state=state,
        actor_id=actor_id,
        purpose=purpose,
        recipient_id=recipient_id,
        evidence=evidence_ref or evidence(),
        sequence=sequence,
        supersedes=supersedes,
    )
