"""Evidence verification that keeps raw source content caller-side.

``verify_evidence`` takes the private source bytes (held only by the caller) and
a claim, and checks two things: that the claim's ``sha256:`` source digest
matches the bytes, and that its character offsets fall within the source. The
raw bytes and the referenced span are never copied into the returned result, a
claim, a reduced decision, or an egress payload. The result carries only a
typed code plus the opaque source ID and digest.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from .contracts import EvidenceCode, EvidenceRef, ExtractionClaim


@dataclass(frozen=True, slots=True)
class EvidenceResult:
    verified: bool
    code: EvidenceCode
    source_id: str
    source_digest: str

    def to_contract_dict(self) -> dict:
        return {
            "schemaVersion": "1.0",
            "verified": self.verified,
            "code": self.code.value,
            "sourceId": self.source_id,
            "sourceDigest": self.source_digest,
        }


def digest_bytes(source_bytes: bytes) -> str:
    return "sha256:" + hashlib.sha256(source_bytes).hexdigest()


def verify_evidence(source_bytes: bytes, claim: ExtractionClaim) -> EvidenceResult:
    """Verify a claim's evidence against caller-held source bytes.

    Digest is checked before offsets so a substituted source is reported as a
    digest mismatch rather than leaking offset information about the wrong
    document. Returns a typed :class:`EvidenceResult`; the raw bytes stay with
    the caller and are never persisted.
    """

    if not isinstance(claim, ExtractionClaim):
        raise ValueError("verify_evidence requires an ExtractionClaim")
    if not isinstance(source_bytes, (bytes, bytearray)):
        raise ValueError("source_bytes must be bytes")

    reference: EvidenceRef = claim.evidence
    if digest_bytes(bytes(source_bytes)) != reference.source_digest:
        return _result(False, EvidenceCode.DIGEST_MISMATCH, reference)
    if reference.end_offset > len(source_bytes):
        return _result(False, EvidenceCode.OFFSET_OUT_OF_RANGE, reference)
    return _result(True, EvidenceCode.VERIFIED, reference)


def _result(verified: bool, code: EvidenceCode, reference: EvidenceRef) -> EvidenceResult:
    return EvidenceResult(
        verified=verified,
        code=code,
        source_id=reference.source_id,
        source_digest=reference.source_digest,
    )
