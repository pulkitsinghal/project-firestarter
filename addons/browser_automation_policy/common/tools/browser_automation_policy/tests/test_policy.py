from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import unittest

from ..contracts import (
    ActionKind,
    ActionProposal,
    AdapterKind,
    CapabilityGrant,
    ConfirmationTier,
    DecisionCode,
    EffectClass,
    Reversibility,
)
from ..evidence import EVIDENCE_KEYS, assert_minimized_envelope, evidence_envelope
from ..policy import BrowserAutomationPolicy
from .common import (
    BASE_PRECONDITIONS,
    candidate,
    confirmation,
    grant,
    observation,
    proposal,
)


class PolicyContractTests(unittest.TestCase):
    def test_unique_semantic_observation_authorizes_handoff_not_execution(self) -> None:
        action = proposal()
        decision = BrowserAutomationPolicy().evaluate(
            grant(), action, observation(), now_tick=100
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.code, DecisionCode.AUTHORIZED_HANDOFF)
        self.assertEqual(decision.handoff["kind"], "future-executor-handoff")
        self.assertIs(decision.handoff["executorConfigured"], False)
        self.assertEqual(decision.handoff["idempotencyKey"], action.idempotency_key)
        self.assertRegex(decision.handoff["handoffNonce"], r"^sha256:[0-9a-f]{64}$")
        handoff_schema = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "schemas"
                / "future-executor-handoff-1.0.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(set(decision.handoff), set(handoff_schema["required"]))
        self.assertLessEqual(
            decision.handoff["expiresAtTick"] - decision.handoff["issuedAtTick"],
            60,
        )

    def test_navigation_requires_action_bound_user_intent(self) -> None:
        action = proposal(
            action=ActionKind.NAVIGATE,
            effect=EffectClass.NAVIGATE,
        )
        policy = BrowserAutomationPolicy()
        denied = policy.evaluate(grant(), action, observation(), now_tick=100)
        self.assertEqual(denied.code, DecisionCode.CONFIRMATION_REQUIRED)
        self.assertEqual(denied.required_confirmation, ConfirmationTier.USER_INTENT)

        allowed = policy.evaluate(
            grant(),
            action,
            observation(),
            now_tick=100,
            confirmation=confirmation(action, ConfirmationTier.USER_INTENT),
        )
        self.assertEqual(allowed.code, DecisionCode.AUTHORIZED_HANDOFF)

    def test_draft_edit_requires_reversal_and_fresh_confirmation(self) -> None:
        missing_undo = replace(
            proposal(
                action=ActionKind.SET_VALUE,
                effect=EffectClass.EDIT_DRAFT,
                reversibility=Reversibility.REVERSIBLE,
            ),
            reversal_action=None,
        )
        denied = BrowserAutomationPolicy().evaluate(
            grant(), missing_undo, observation(), now_tick=100
        )
        self.assertEqual(denied.code, DecisionCode.REVERSAL_REQUIRED)

        incompatible_undo = replace(
            proposal(
                proposal_id="proposal-bad-undo",
                idempotency_key="idempotency-bad-undo",
                action=ActionKind.SET_VALUE,
                effect=EffectClass.EDIT_DRAFT,
            ),
            reversal_action=ActionKind.NAVIGATE,
        )
        denied = BrowserAutomationPolicy().evaluate(
            grant(), incompatible_undo, observation(), now_tick=100
        )
        self.assertEqual(denied.code, DecisionCode.REVERSAL_REQUIRED)

        action = proposal(
            proposal_id="proposal-edit",
            idempotency_key="idempotency-edit",
            action=ActionKind.SET_VALUE,
            effect=EffectClass.EDIT_DRAFT,
        )
        denied = BrowserAutomationPolicy().evaluate(
            grant(), action, observation(), now_tick=100
        )
        self.assertEqual(denied.code, DecisionCode.CONFIRMATION_REQUIRED)
        self.assertEqual(denied.required_confirmation, ConfirmationTier.ACTION_BOUND)

    def test_external_submit_is_irreversible_and_tier_three(self) -> None:
        action = proposal(
            action=ActionKind.SUBMIT,
            effect=EffectClass.EXTERNAL_SUBMIT,
        )
        policy = BrowserAutomationPolicy()
        denied = policy.evaluate(grant(), action, observation(), now_tick=100)
        self.assertEqual(denied.required_confirmation, ConfirmationTier.OWNER_EXTERNAL)
        self.assertEqual(denied.code, DecisionCode.CONFIRMATION_REQUIRED)
        allowed = policy.evaluate(
            grant(),
            action,
            observation(),
            now_tick=100,
            confirmation=confirmation(action, ConfirmationTier.OWNER_EXTERNAL),
        )
        self.assertEqual(allowed.code, DecisionCode.AUTHORIZED_HANDOFF)

    def test_action_effect_mismatch_is_typed_refusal(self) -> None:
        action = proposal(
            action=ActionKind.DELETE,
            effect=EffectClass.OBSERVE,
        )
        decision = BrowserAutomationPolicy().evaluate(
            grant(), action, observation(), now_tick=100
        )
        self.assertEqual(decision.code, DecisionCode.INTENT_UNSUPPORTED)

    def test_preconditions_and_postconditions_are_mandatory(self) -> None:
        missing_precondition = proposal(
            preconditions=BASE_PRECONDITIONS - {"target-actionable"}
        )
        decision = BrowserAutomationPolicy().evaluate(
            grant(), missing_precondition, observation(), now_tick=100
        )
        self.assertEqual(decision.code, DecisionCode.PRECONDITION_FAILED)

        missing_postcondition = proposal(
            proposal_id="proposal-post",
            idempotency_key="idempotency-post",
            postconditions=frozenset(),
        )
        decision = BrowserAutomationPolicy().evaluate(
            grant(), missing_postcondition, observation(), now_tick=100
        )
        self.assertEqual(decision.code, DecisionCode.POSTCONDITION_REQUIRED)

    def test_focus_is_reasserted_before_typed_input(self) -> None:
        action = proposal(
            action=ActionKind.SET_VALUE,
            effect=EffectClass.EDIT_DRAFT,
        )
        decision = BrowserAutomationPolicy().evaluate(
            grant(),
            action,
            observation(focus_confirmed=False),
            now_tick=100,
            confirmation=confirmation(action, ConfirmationTier.ACTION_BOUND),
        )
        self.assertEqual(decision.code, DecisionCode.PRECONDITION_FAILED)

    def test_prompt_injection_signal_is_data_and_raises_confirmation(self) -> None:
        action = proposal()
        signaled = observation(prompt_signals=("visible-page-command",))
        policy = BrowserAutomationPolicy()
        denied = policy.evaluate(grant(), action, signaled, now_tick=100)
        self.assertEqual(denied.code, DecisionCode.PROMPT_INJECTION_REVIEW)
        self.assertEqual(denied.required_confirmation, ConfirmationTier.ACTION_BOUND)

        allowed = policy.evaluate(
            grant(),
            action,
            signaled,
            now_tick=100,
            confirmation=confirmation(action, ConfirmationTier.ACTION_BOUND),
        )
        self.assertEqual(allowed.code, DecisionCode.AUTHORIZED_HANDOFF)
        self.assertNotIn("visible-page-command", repr(allowed.handoff))

    def test_expired_or_changed_confirmation_is_stale(self) -> None:
        action = proposal(
            action=ActionKind.NAVIGATE,
            effect=EffectClass.NAVIGATE,
        )
        expired = confirmation(
            action,
            ConfirmationTier.USER_INTENT,
            expires_at_tick=99,
        )
        decision = BrowserAutomationPolicy().evaluate(
            grant(), action, observation(), now_tick=100, confirmation=expired
        )
        self.assertEqual(decision.code, DecisionCode.CONFIRMATION_STALE)

        boundary = confirmation(
            action,
            ConfirmationTier.USER_INTENT,
            expires_at_tick=100,
        )
        decision = BrowserAutomationPolicy().evaluate(
            grant(), action, observation(), now_tick=100, confirmation=boundary
        )
        self.assertEqual(decision.code, DecisionCode.CONFIRMATION_STALE)

        changed = confirmation(
            action,
            ConfirmationTier.USER_INTENT,
            payload_digest="sha256:" + "f" * 64,
        )
        decision = BrowserAutomationPolicy().evaluate(
            grant(), action, observation(), now_tick=100, confirmation=changed
        )
        self.assertEqual(decision.code, DecisionCode.CONFIRMATION_STALE)

    def test_evidence_is_reconstructed_from_exact_allowlist(self) -> None:
        action = proposal()
        decision = BrowserAutomationPolicy().evaluate(
            grant(), action, observation(), now_tick=100
        )
        envelope = evidence_envelope(decision, action.binding)
        self.assertEqual(set(envelope), EVIDENCE_KEYS)
        serialized = repr(envelope).lower()
        for marker in (
            "page text",
            "selector",
            "cookie",
            "credential",
            "query",
            "private",
        ):
            self.assertNotIn(marker, serialized)
        with self.assertRaises(ValueError):
            assert_minimized_envelope({**envelope, "pageText": "synthetic-private"})

    def test_capability_grant_cannot_be_expanded_by_proposal(self) -> None:
        action = proposal()
        limited = grant(allowed_effects=frozenset({EffectClass.NAVIGATE}))
        decision = BrowserAutomationPolicy().evaluate(
            limited, action, observation(), now_tick=100
        )
        self.assertEqual(decision.code, DecisionCode.EFFECT_NOT_ALLOWED)

        geometry_only = grant(
            allowed_adapters=frozenset({AdapterKind.RELATIVE_XY})
        )
        decision = BrowserAutomationPolicy().evaluate(
            geometry_only, action, observation(), now_tick=100
        )
        self.assertEqual(decision.code, DecisionCode.ADAPTER_NOT_ALLOWED)

        confused_target = replace(
            action.target,
            contract_id="delete-account",
            accessible_name_token="delete-account",
        )
        confused_action = proposal(
            proposal_id="proposal-target-confusion",
            idempotency_key="idempotency-target-confusion",
            action=ActionKind.ACTIVATE,
            effect=EffectClass.NAVIGATE,
            target_contract=confused_target,
        )
        confused_candidate = candidate(
            contract_id="delete-account",
            accessible_name_token="delete-account",
        )
        decision = BrowserAutomationPolicy().evaluate(
            grant(),
            confused_action,
            observation(confused_candidate),
            now_tick=100,
        )
        self.assertEqual(decision.code, DecisionCode.TARGET_NOT_ALLOWED)

    def test_handoff_expiry_is_bounded_by_grant_expiry(self) -> None:
        action = proposal()
        short_grant = replace(grant(), expires_at_tick=101)
        decision = BrowserAutomationPolicy().evaluate(
            short_grant, action, observation(), now_tick=100
        )
        self.assertEqual(decision.code, DecisionCode.AUTHORIZED_HANDOFF)
        self.assertEqual(decision.handoff["expiresAtTick"], 101)

    def test_action_contract_round_trip_recomputes_canonical_digest(self) -> None:
        action = proposal(
            action=ActionKind.SET_VALUE,
            effect=EffectClass.EDIT_DRAFT,
        )
        encoded = action.to_contract_dict()
        proposal_schema = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "schemas"
                / "action-proposal-1.0.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(set(encoded), set(proposal_schema["required"]))
        self.assertEqual(ActionProposal.from_contract_dict(encoded), action)

        with self.assertRaisesRegex(ValueError, "fields do not match"):
            ActionProposal.from_contract_dict({**encoded, "pageText": "untrusted"})
        with self.assertRaisesRegex(ValueError, "canonical proposal"):
            ActionProposal.from_contract_dict(
                {**encoded, "proposalDigest": "sha256:" + "f" * 64}
            )

        action_grant = grant()
        encoded_grant = action_grant.to_contract_dict()
        grant_schema = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "schemas"
                / "capability-grant-1.0.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(set(encoded_grant), set(grant_schema["required"]))
        self.assertEqual(
            CapabilityGrant.from_contract_dict(encoded_grant),
            action_grant,
        )
        with self.assertRaisesRegex(ValueError, "fields do not match"):
            CapabilityGrant.from_contract_dict(
                {**encoded_grant, "pageText": "untrusted"}
            )


if __name__ == "__main__":
    unittest.main()
