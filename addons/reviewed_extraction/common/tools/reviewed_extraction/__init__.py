"""Source-only, human-reviewed structured-extraction contract and egress reducer."""

from .contracts import (
    ClaimState,
    EgressCode,
    EvidenceCode,
    EvidenceRef,
    ExtractionClaim,
    Purpose,
    ReducedDecision,
    ReductionCode,
)
from .egress import build_egress, classify
from .evidence import EvidenceResult, verify_evidence
from .reducer import reduce_claims

__all__ = [
    "ClaimState",
    "EgressCode",
    "EvidenceCode",
    "EvidenceRef",
    "EvidenceResult",
    "ExtractionClaim",
    "Purpose",
    "ReducedDecision",
    "ReductionCode",
    "build_egress",
    "classify",
    "reduce_claims",
    "verify_evidence",
]

__version__ = "0.1.0"
