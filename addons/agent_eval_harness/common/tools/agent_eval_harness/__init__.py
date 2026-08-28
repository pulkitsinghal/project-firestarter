"""Source-only, deterministic agent-evaluation harness contracts."""

from .contracts import (
    AdvisoryCritique,
    CandidateOutput,
    Check,
    CheckKind,
    CheckOutcome,
    CheckResult,
    CritiqueVerdict,
    EvalCase,
    EvalResult,
    Evidence,
    NumericComparator,
    ResultState,
)
from .harness import evaluate

__all__ = [
    "AdvisoryCritique",
    "CandidateOutput",
    "Check",
    "CheckKind",
    "CheckOutcome",
    "CheckResult",
    "CritiqueVerdict",
    "EvalCase",
    "EvalResult",
    "Evidence",
    "NumericComparator",
    "ResultState",
    "evaluate",
]

__version__ = "0.1.0"
