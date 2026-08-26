"""Deterministic reducer: fold a claim set into one decision per field path.

The reducer is pure code. A model may *propose* claims, but it never authors the
final decision or the released value: those are computed here from human review
states with a fixed, documented precedence.

Precedence rules (applied per field path, in order):

1. Supersession removes claims from consideration. A claim is inactive if its
   own state is ``superseded`` or if its ``claim_id`` appears in the
   ``supersedes`` set of any other claim for the same field path.
2. An explicit ``conflicted`` state on any active claim withholds the field
   (``withheld-conflicted``) regardless of any releasable claim present.
3. Among active releasable claims (``confirmed`` / ``corrected``),
   ``corrected`` outranks ``confirmed`` (correction precedence). The winner is
   the highest-precedence claim, ties broken by higher ``sequence`` then by
   ``claim_id`` (stable and deterministic).
4. If two or more active releasable claims share the top precedence tier but
   carry *different* values, the field is withheld as ``withheld-conflicted``
   (genuine disagreement the code will not silently pick between).
5. With no active releasable claim, the withheld reason is chosen from the
   remaining active states by priority ``proposed`` > ``unknown`` > ``omitted``;
   if no active claim remains, the field is ``withheld-superseded``.
"""

from __future__ import annotations

from typing import Dict, Iterable, List

from .contracts import (
    ClaimState,
    ExtractionClaim,
    ReducedDecision,
    ReductionCode,
    STATE_PRECEDENCE,
)


def _withheld(field_path: str, code: ReductionCode, active, superseded) -> ReducedDecision:
    return ReducedDecision(
        field_path=field_path,
        outcome=code,
        released_value=None,
        winning_claim_id=None,
        actor_id=None,
        purpose=None,
        recipient_id=None,
        evidence=None,
        contributing_claim_ids=tuple(sorted(claim.claim_id for claim in active)),
        superseded_claim_ids=tuple(sorted(superseded)),
    )


def _reduce_group(field_path: str, group: List[ExtractionClaim]) -> ReducedDecision:
    superseded_ids = set()
    group_ids = {claim.claim_id for claim in group}
    for claim in group:
        if claim.state is ClaimState.SUPERSEDED:
            superseded_ids.add(claim.claim_id)
        for target_id in claim.supersedes:
            if target_id in group_ids:
                superseded_ids.add(target_id)

    active = [claim for claim in group if claim.claim_id not in superseded_ids]
    superseded_in_group = superseded_ids & group_ids
    conflicted = any(claim.state is ClaimState.CONFLICTED for claim in active)
    releasable = [claim for claim in active if claim.state in STATE_PRECEDENCE]

    if releasable and not conflicted:
        top_tier = max(STATE_PRECEDENCE[claim.state] for claim in releasable)
        peers = [
            claim for claim in releasable if STATE_PRECEDENCE[claim.state] == top_tier
        ]
        if len({claim.value for claim in peers}) > 1:
            return _withheld(
                field_path,
                ReductionCode.WITHHELD_CONFLICTED,
                active,
                superseded_in_group,
            )
        winner = max(peers, key=lambda claim: (claim.sequence, claim.claim_id))
        outcome = (
            ReductionCode.RELEASABLE_CORRECTED
            if winner.state is ClaimState.CORRECTED
            else ReductionCode.RELEASABLE_CONFIRMED
        )
        return ReducedDecision(
            field_path=field_path,
            outcome=outcome,
            released_value=winner.value,
            winning_claim_id=winner.claim_id,
            actor_id=winner.actor_id,
            purpose=winner.purpose,
            recipient_id=winner.recipient_id,
            evidence=winner.evidence,
            contributing_claim_ids=tuple(
                sorted(claim.claim_id for claim in active)
            ),
            superseded_claim_ids=tuple(sorted(superseded_in_group)),
        )

    if conflicted:
        code = ReductionCode.WITHHELD_CONFLICTED
    elif not active:
        code = ReductionCode.WITHHELD_SUPERSEDED
    else:
        states = {claim.state for claim in active}
        if ClaimState.PROPOSED in states:
            code = ReductionCode.WITHHELD_PROPOSED
        elif ClaimState.UNKNOWN in states:
            code = ReductionCode.WITHHELD_UNKNOWN
        elif ClaimState.OMITTED in states:
            code = ReductionCode.WITHHELD_OMITTED
        else:
            code = ReductionCode.WITHHELD_SUPERSEDED
    return _withheld(field_path, code, active, superseded_in_group)


def reduce_claims(claims: Iterable[ExtractionClaim]) -> Dict[str, ReducedDecision]:
    """Fold claims into one :class:`ReducedDecision` per field path.

    Raises ``ValueError`` on a duplicate ``claim_id`` (a corrupt claim set is
    never silently reduced). The result is ordered by field path so the fold is
    stable across runs.
    """

    materialized = list(claims)
    seen_ids = set()
    groups: Dict[str, List[ExtractionClaim]] = {}
    for claim in materialized:
        if not isinstance(claim, ExtractionClaim):
            raise ValueError("reduce_claims requires ExtractionClaim inputs")
        if claim.claim_id in seen_ids:
            raise ValueError(f"duplicate claim id: {claim.claim_id}")
        seen_ids.add(claim.claim_id)
        groups.setdefault(claim.field_path, []).append(claim)

    return {
        field_path: _reduce_group(field_path, groups[field_path])
        for field_path in sorted(groups)
    }
