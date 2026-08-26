"""Deterministic reducer: (case + candidate + input fixtures) -> result.

The reducer is a pure function of its inputs. It performs no I/O, spawns no
process, and consults no clock. It verifies content-addressed digests, computes
every declared check, and reduces the blocking checks to a terminal verdict.

Critique quarantine
-------------------
`_score` is the sole authority for the verdict. Its only argument is the tuple
of `CheckResult` objects; it has no parameter through which an advisory critique
could reach it. `evaluate` computes the verdict with `_score` FIRST and only
then records whether a critique was present. There is no code path by which a
critique's fields influence the state, so a critique can never flip a blocking
verdict. See the two call sites flagged below.
"""

from __future__ import annotations

from typing import Mapping, Optional, Tuple

from . import checks
from .contracts import (
    CandidateOutput,
    canonical_digest,
    CheckOutcome,
    CheckResult,
    EvalCase,
    EvalResult,
    Evidence,
    ResultState,
)


def _score(check_results: Tuple[CheckResult, ...]) -> ResultState:
    """Reduce check outcomes to a terminal state. Blocking checks alone decide
    PASSED/FAILED. A non-blocking signal only raises NEEDS_REVIEW. This function
    receives nothing but check outcomes, so no advisory input can reach it."""

    blocking = [item for item in check_results if item.blocking]
    non_blocking = [item for item in check_results if not item.blocking]
    if any(item.outcome is CheckOutcome.UNAVAILABLE for item in blocking):
        return ResultState.UNAVAILABLE
    if any(item.outcome is CheckOutcome.VIOLATED for item in blocking):
        return ResultState.FAILED
    if any(
        item.outcome in (CheckOutcome.VIOLATED, CheckOutcome.UNAVAILABLE)
        for item in non_blocking
    ):
        return ResultState.NEEDS_REVIEW
    return ResultState.PASSED


def _verify_evidence(candidate: CandidateOutput) -> dict:
    """Return a map evidence_id -> values dict when the digest verifies, else
    None. A tampered or mismatched digest makes that evidence unusable."""

    verified: dict = {}
    for item in candidate.evidence:
        verified[item.evidence_id] = item.values if item.verified else None
    return verified


def _check_outcome(check, verified: Mapping[str, Optional[dict]]) -> CheckOutcome:
    values = verified.get(check.evidence_id)
    if values is None:  # evidence absent or digest did not verify
        return CheckOutcome.UNAVAILABLE
    if check.field_token not in values:
        return CheckOutcome.UNAVAILABLE
    return checks.evaluate_value(check.kind, values[check.field_token], check.params)


def _input_available(
    case: EvalCase, input_fixtures: Mapping[str, dict]
) -> bool:
    values = input_fixtures.get(case.input_fixture_id)
    if values is None:
        return False
    return canonical_digest(values) == case.input_fixture_digest


def evaluate(
    case: EvalCase,
    candidate: CandidateOutput,
    input_fixtures: Optional[Mapping[str, dict]] = None,
) -> EvalResult:
    """Score one candidate against one case. Fails closed: the case and
    candidate are already parsed by their contract constructors, which reject
    unknown fields and unknown check kinds before reaching here."""

    if candidate.case_id != case.case_id:
        raise ValueError("candidate case id does not match case")
    input_fixtures = input_fixtures or {}

    verified = _verify_evidence(candidate)
    evidence_verified = all(values is not None for values in verified.values())

    check_results = tuple(
        CheckResult(
            check_id=check.check_id,
            kind=check.kind,
            blocking=check.blocking,
            outcome=_check_outcome(check, verified),
        )
        for check in case.checks
    )

    # Verdict is decided here, from check outcomes only. The advisory critique
    # is NOT in scope for this computation.
    if not _input_available(case, input_fixtures):
        state = ResultState.UNAVAILABLE
    else:
        state = _score(check_results)

    # Only AFTER the verdict is fixed do we record the critique's presence. The
    # critique's verdict/note never touch `state`.
    advisory_critique_recorded = candidate.critique is not None

    return EvalResult(
        case_id=case.case_id,
        state=state,
        check_results=check_results,
        evidence_verified=evidence_verified,
        advisory_critique_recorded=advisory_critique_recorded,
    )
