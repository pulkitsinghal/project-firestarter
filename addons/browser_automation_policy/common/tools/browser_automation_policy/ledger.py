"""In-memory reference ledger with deterministic replay reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Dict, Optional, Tuple

from .contracts import ActionProposal, DecisionCode, LedgerStatus


@dataclass(frozen=True, slots=True)
class LedgerRecord:
    proposal_id: str
    idempotency_key: str
    proposal_digest: str
    status: LedgerStatus
    attempt: int


class ActionLedger:
    """Authoritative proposal ledger for a future durable implementation.

    The reference is intentionally memory-only and effect-free. An integrating
    product must persist the same state machine before enabling an executor.
    """

    def __init__(self) -> None:
        self._by_key: Dict[str, LedgerRecord] = {}
        self._lock = RLock()

    def preflight(self, proposal: ActionProposal) -> Optional[DecisionCode]:
        with self._lock:
            current = self._by_key.get(proposal.idempotency_key)
            if current is None:
                return None
            if current.proposal_digest != proposal.proposal_digest:
                return DecisionCode.IDEMPOTENCY_COLLISION
            if current.status is LedgerStatus.INDETERMINATE:
                return DecisionCode.PRIOR_OUTCOME_INDETERMINATE
            return DecisionCode.ACTION_REPLAYED

    def plan(self, proposal: ActionProposal) -> LedgerRecord:
        with self._lock:
            refusal = self.preflight(proposal)
            if refusal is not None:
                raise ValueError(refusal.value)
            record = LedgerRecord(
                proposal_id=proposal.proposal_id,
                idempotency_key=proposal.idempotency_key,
                proposal_digest=proposal.proposal_digest,
                status=LedgerStatus.PLANNED,
                attempt=1,
            )
            self._by_key[proposal.idempotency_key] = record
            return record

    def transition(
        self,
        idempotency_key: str,
        expected: LedgerStatus,
        target: LedgerStatus,
    ) -> LedgerRecord:
        with self._lock:
            current = self._by_key[idempotency_key]
            if current.status is not expected:
                raise ValueError(
                    f"invalid ledger transition {current.status.value}->{target.value}"
                )
            allowed: Tuple[Tuple[LedgerStatus, LedgerStatus], ...] = (
                (LedgerStatus.PLANNED, LedgerStatus.CONFIRMED),
                (LedgerStatus.PLANNED, LedgerStatus.HANDED_OFF),
                (LedgerStatus.CONFIRMED, LedgerStatus.HANDED_OFF),
                (LedgerStatus.HANDED_OFF, LedgerStatus.SUCCEEDED),
                (LedgerStatus.HANDED_OFF, LedgerStatus.FAILED),
                (LedgerStatus.HANDED_OFF, LedgerStatus.INDETERMINATE),
            )
            if (expected, target) not in allowed:
                raise ValueError(
                    f"forbidden ledger transition {expected.value}->{target.value}"
                )
            updated = LedgerRecord(
                proposal_id=current.proposal_id,
                idempotency_key=current.idempotency_key,
                proposal_digest=current.proposal_digest,
                status=target,
                attempt=current.attempt,
            )
            self._by_key[idempotency_key] = updated
            return updated

    def get(self, idempotency_key: str) -> Optional[LedgerRecord]:
        with self._lock:
            return self._by_key.get(idempotency_key)
