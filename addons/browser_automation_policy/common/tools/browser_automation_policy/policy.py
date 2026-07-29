"""Policy gate for typed proposals and future-executor handoffs.

This module has no executor and performs no I/O. It evaluates already-minimized
observations, records authorization state, and returns a content-free handoff.
"""

from __future__ import annotations

from typing import Optional, Tuple

from .adapters.citrix_remote import CitrixObservation, validate_citrix
from .adapters.relative_xy import validate_geometry
from .adapters.semantic_dom import resolve_semantic
from .contracts import (
    ActionKind,
    ActionProposal,
    AdapterKind,
    CapabilityGrant,
    Confirmation,
    ConfirmationTier,
    Decision,
    DecisionCode,
    EffectClass,
    LedgerStatus,
    RelativeTargetContract,
    Reversibility,
    RemoteTargetContract,
    SemanticObservation,
    TargetContract,
)
from .evidence import future_executor_handoff
from .ledger import ActionLedger


ACTION_EFFECTS = {
    ActionKind.OBSERVE: EffectClass.OBSERVE,
    ActionKind.FOCUS: EffectClass.OBSERVE,
    ActionKind.ACTIVATE: EffectClass.NAVIGATE,
    ActionKind.NAVIGATE: EffectClass.NAVIGATE,
    ActionKind.SET_VALUE: EffectClass.EDIT_DRAFT,
    ActionKind.CLEAR_VALUE: EffectClass.EDIT_DRAFT,
    ActionKind.SELECT: EffectClass.EDIT_DRAFT,
    ActionKind.EXTERNAL_SEND: EffectClass.EXTERNAL_SUBMIT,
    ActionKind.SUBMIT: EffectClass.EXTERNAL_SUBMIT,
    ActionKind.UPLOAD: EffectClass.EXTERNAL_SUBMIT,
    ActionKind.DELETE: EffectClass.DESTRUCTIVE,
    ActionKind.GRANT_PERMISSION: EffectClass.DESTRUCTIVE,
}

BASE_PRECONDITIONS = frozenset(
    {
        "task-bound",
        "document-current",
        "frame-current",
        "origin-allowed",
        "target-unique",
        "target-actionable",
        "payload-bound",
    }
)

FOCUS_ACTIONS = frozenset(
    {
        ActionKind.SET_VALUE,
        ActionKind.CLEAR_VALUE,
        ActionKind.SELECT,
        ActionKind.EXTERNAL_SEND,
        ActionKind.SUBMIT,
        ActionKind.UPLOAD,
    }
)

MUTATING_EFFECTS = frozenset(
    {
        EffectClass.EDIT_DRAFT,
        EffectClass.EXTERNAL_SUBMIT,
        EffectClass.DESTRUCTIVE,
    }
)

REQUIRED_POSTCONDITION = {
    EffectClass.OBSERVE: "state-observed",
    EffectClass.NAVIGATE: "navigation-reconciled",
    EffectClass.EDIT_DRAFT: "draft-reconciled",
    EffectClass.EXTERNAL_SUBMIT: "external-effect-reconciled",
    EffectClass.DESTRUCTIVE: "destructive-effect-reconciled",
}

EFFECT_CONFIRMATION = {
    EffectClass.OBSERVE: ConfirmationTier.NONE,
    EffectClass.NAVIGATE: ConfirmationTier.USER_INTENT,
    EffectClass.EDIT_DRAFT: ConfirmationTier.ACTION_BOUND,
    EffectClass.EXTERNAL_SUBMIT: ConfirmationTier.OWNER_EXTERNAL,
    EffectClass.DESTRUCTIVE: ConfirmationTier.OWNER_EXTERNAL,
}


class BrowserAutomationPolicy:
    """Pure policy reference with exactly-once handoff semantics."""

    def __init__(self, ledger: Optional[ActionLedger] = None) -> None:
        self.ledger = ledger or ActionLedger()

    @staticmethod
    def _decision(
        proposal: ActionProposal,
        code: DecisionCode,
        tier: ConfirmationTier,
        *,
        allowed: bool = False,
        handoff: Optional[dict] = None,
    ) -> Decision:
        return Decision(
            allowed=allowed,
            code=code,
            required_confirmation=tier,
            adapter=proposal.adapter,
            proposal_id=proposal.proposal_id,
            handoff=handoff,
        )

    @staticmethod
    def _required_tier(
        proposal: ActionProposal,
        prompt_injection_signaled: bool,
    ) -> ConfirmationTier:
        tier = EFFECT_CONFIRMATION[proposal.effect]
        if proposal.adapter is AdapterKind.CITRIX_REMOTE:
            tier = max(tier, ConfirmationTier.ACTION_BOUND)
        if prompt_injection_signaled:
            tier = max(tier, ConfirmationTier.ACTION_BOUND)
        return ConfirmationTier(tier)

    def _common_preflight(
        self,
        grant: CapabilityGrant,
        proposal: ActionProposal,
        *,
        now_tick: int,
        prompt_injection_signaled: bool,
    ) -> Tuple[Optional[Decision], ConfirmationTier]:
        tier = self._required_tier(proposal, prompt_injection_signaled)

        if now_tick >= grant.expires_at_tick or now_tick >= proposal.expires_at_tick:
            return self._decision(
                proposal, DecisionCode.PRECONDITION_FAILED, tier
            ), tier
        if proposal.task_id != grant.task_id:
            return self._decision(
                proposal, DecisionCode.PRECONDITION_FAILED, tier
            ), tier
        if proposal.adapter not in grant.allowed_adapters:
            return self._decision(proposal, DecisionCode.ADAPTER_NOT_ALLOWED, tier), tier
        if proposal.effect not in grant.allowed_effects:
            return self._decision(proposal, DecisionCode.EFFECT_NOT_ALLOWED, tier), tier
        if ACTION_EFFECTS.get(proposal.action) is not proposal.effect:
            return self._decision(proposal, DecisionCode.INTENT_UNSUPPORTED, tier), tier
        if (
            proposal.adapter,
            proposal.action,
            proposal.effect,
            proposal.target.kind,
            proposal.target.contract_digest,
        ) not in grant.allowed_action_targets:
            return self._decision(proposal, DecisionCode.TARGET_NOT_ALLOWED, tier), tier

        origin_chain = proposal.binding.origin_ids
        if any(origin_id not in grant.allowed_origin_ids for origin_id in origin_chain):
            return self._decision(proposal, DecisionCode.ORIGIN_NOT_ALLOWED, tier), tier
        if origin_chain not in grant.allowed_frame_origin_chains:
            code = (
                DecisionCode.CROSS_ORIGIN_FRAME_BLOCKED
                if len(set(origin_chain)) > 1
                else DecisionCode.FRAME_NOT_ALLOWED
            )
            return self._decision(proposal, code, tier), tier

        required_preconditions = BASE_PRECONDITIONS
        if proposal.action in FOCUS_ACTIONS:
            required_preconditions = required_preconditions | {"focus-current"}
        if not required_preconditions.issubset(proposal.preconditions):
            return self._decision(
                proposal, DecisionCode.PRECONDITION_FAILED, tier
            ), tier
        expected_postcondition = REQUIRED_POSTCONDITION[proposal.effect]
        if expected_postcondition not in proposal.postconditions:
            return self._decision(
                proposal, DecisionCode.POSTCONDITION_REQUIRED, tier
            ), tier
        if (
            proposal.effect is EffectClass.EDIT_DRAFT
            and (
                proposal.reversibility is not Reversibility.REVERSIBLE
                or proposal.reversal_action
                not in {
                    ActionKind.SET_VALUE: {
                        ActionKind.SET_VALUE,
                        ActionKind.CLEAR_VALUE,
                    },
                    ActionKind.CLEAR_VALUE: {ActionKind.SET_VALUE},
                    ActionKind.SELECT: {ActionKind.SELECT},
                }.get(proposal.action, set())
                or proposal.reversal_payload_digest is None
            )
        ):
            return self._decision(
                proposal, DecisionCode.REVERSAL_REQUIRED, tier
            ), tier
        if (
            proposal.effect in {EffectClass.EXTERNAL_SUBMIT, EffectClass.DESTRUCTIVE}
            and (
                proposal.reversibility is not Reversibility.IRREVERSIBLE
                or proposal.reversal_action is not None
                or proposal.reversal_payload_digest is not None
            )
        ):
            return self._decision(
                proposal, DecisionCode.REVERSAL_REQUIRED, tier
            ), tier

        replay = self.ledger.preflight(proposal)
        if replay is not None:
            return self._decision(proposal, replay, tier), tier
        return None, tier

    @staticmethod
    def _confirmation_valid(
        proposal: ActionProposal,
        confirmation: Optional[Confirmation],
        tier: ConfirmationTier,
        now_tick: int,
    ) -> Optional[DecisionCode]:
        if tier is ConfirmationTier.NONE:
            return None
        if confirmation is None:
            return DecisionCode.CONFIRMATION_REQUIRED
        if confirmation.tier < tier:
            return DecisionCode.CONFIRMATION_REQUIRED
        if (
            confirmation.expires_at_tick <= now_tick
            or confirmation.proposal_id != proposal.proposal_id
            or confirmation.proposal_digest != proposal.proposal_digest
            or confirmation.payload_digest != proposal.payload_digest
            or confirmation.document_id != proposal.binding.document_id
            or confirmation.document_generation
            != proposal.binding.document_generation
            or confirmation.surface_generation
            != proposal.binding.surface_generation
        ):
            return DecisionCode.CONFIRMATION_STALE
        return None

    def _authorize_handoff(
        self,
        grant: CapabilityGrant,
        proposal: ActionProposal,
        tier: ConfirmationTier,
        now_tick: int,
    ) -> Decision:
        try:
            self.ledger.plan(proposal)
        except ValueError as error:
            return self._decision(
                proposal,
                DecisionCode(str(error)),
                tier,
            )
        if tier is not ConfirmationTier.NONE:
            self.ledger.transition(
                proposal.idempotency_key,
                LedgerStatus.PLANNED,
                LedgerStatus.CONFIRMED,
            )
            expected = LedgerStatus.CONFIRMED
        else:
            expected = LedgerStatus.PLANNED
        self.ledger.transition(
            proposal.idempotency_key,
            expected,
            LedgerStatus.HANDED_OFF,
        )
        handoff = future_executor_handoff(
            proposal,
            grant_id=grant.grant_id,
            grant_expires_at_tick=grant.expires_at_tick,
            confirmation_tier=tier,
            issued_at_tick=now_tick,
            expires_at_tick=min(
                proposal.expires_at_tick,
                grant.expires_at_tick,
                now_tick + 60,
            ),
        )
        return self._decision(
            proposal,
            DecisionCode.AUTHORIZED_HANDOFF,
            tier,
            allowed=True,
            handoff=handoff,
        )

    def evaluate(
        self,
        grant: CapabilityGrant,
        proposal: ActionProposal,
        observation: SemanticObservation,
        *,
        now_tick: int,
        confirmation: Optional[Confirmation] = None,
    ) -> Decision:
        """Evaluate semantic DOM first, with an explicitly bounded XY fallback."""

        prompt_signal = bool(observation.prompt_injection_signal_ids)
        refusal, tier = self._common_preflight(
            grant,
            proposal,
            now_tick=now_tick,
            prompt_injection_signaled=prompt_signal,
        )
        if refusal is not None:
            return refusal
        if proposal.binding != observation.binding:
            if confirmation is not None:
                return self._decision(
                    proposal, DecisionCode.CONFIRMATION_STALE, tier
                )
            if proposal.binding.document_id != observation.binding.document_id:
                return self._decision(
                    proposal, DecisionCode.DOCUMENT_CHANGED, tier
                )
            if (
                proposal.binding.frame_ids != observation.binding.frame_ids
                or proposal.binding.frame_document_ids
                != observation.binding.frame_document_ids
                or proposal.binding.frame_generations
                != observation.binding.frame_generations
            ):
                return self._decision(proposal, DecisionCode.FRAME_CHANGED, tier)
            return self._decision(proposal, DecisionCode.STALE_HANDLE, tier)
        if proposal.action in FOCUS_ACTIONS and not observation.focus_confirmed:
            return self._decision(
                proposal, DecisionCode.PRECONDITION_FAILED, tier
            )

        if isinstance(proposal.target, (TargetContract, RelativeTargetContract)):
            candidate, semantic_code = resolve_semantic(
                proposal.target,
                proposal.binding,
                observation,
            )
        else:
            candidate, semantic_code = None, DecisionCode.INTENT_UNSUPPORTED
        if proposal.adapter is AdapterKind.SEMANTIC_DOM:
            if not isinstance(proposal.target, TargetContract):
                return self._decision(
                    proposal, DecisionCode.INTENT_UNSUPPORTED, tier
                )
            if semantic_code is not None:
                return self._decision(proposal, semantic_code, tier)
        elif proposal.adapter is AdapterKind.RELATIVE_XY:
            if not isinstance(proposal.target, RelativeTargetContract):
                return self._decision(
                    proposal, DecisionCode.INTENT_UNSUPPORTED, tier
                )
            if semantic_code is not DecisionCode.SEMANTIC_REQUIRED or candidate is None:
                code = semantic_code or DecisionCode.GEOMETRY_NOT_ALLOWED
                return self._decision(proposal, code, tier)
            if not grant.allow_geometry_fallback:
                return self._decision(
                    proposal, DecisionCode.GEOMETRY_NOT_ALLOWED, tier
                )
            geometry_code = validate_geometry(
                candidate,
                proposal.target,
            )
            if geometry_code is not None:
                return self._decision(proposal, geometry_code, tier)
        else:
            return self._decision(
                proposal, DecisionCode.ADAPTER_NOT_ALLOWED, tier
            )

        confirmation_code = self._confirmation_valid(
            proposal, confirmation, tier, now_tick
        )
        if confirmation_code is not None:
            if (
                prompt_signal
                and confirmation_code is DecisionCode.CONFIRMATION_REQUIRED
            ):
                confirmation_code = DecisionCode.PROMPT_INJECTION_REVIEW
            return self._decision(proposal, confirmation_code, tier)
        return self._authorize_handoff(grant, proposal, tier, now_tick)

    def evaluate_citrix(
        self,
        grant: CapabilityGrant,
        proposal: ActionProposal,
        observation: CitrixObservation,
        *,
        now_tick: int,
        confirmation: Optional[Confirmation] = None,
    ) -> Decision:
        refusal, tier = self._common_preflight(
            grant,
            proposal,
            now_tick=now_tick,
            prompt_injection_signaled=False,
        )
        if refusal is not None:
            return refusal
        if proposal.adapter is not AdapterKind.CITRIX_REMOTE:
            return self._decision(
                proposal, DecisionCode.ADAPTER_NOT_ALLOWED, tier
            )
        if not isinstance(proposal.target, RemoteTargetContract):
            return self._decision(
                proposal, DecisionCode.INTENT_UNSUPPORTED, tier
            )
        adapter_code = validate_citrix(
            observation,
            proposal.target,
        )
        if adapter_code is not None:
            return self._decision(proposal, adapter_code, tier)
        confirmation_code = self._confirmation_valid(
            proposal, confirmation, tier, now_tick
        )
        if confirmation_code is not None:
            return self._decision(proposal, confirmation_code, tier)
        return self._authorize_handoff(grant, proposal, tier, now_tick)
