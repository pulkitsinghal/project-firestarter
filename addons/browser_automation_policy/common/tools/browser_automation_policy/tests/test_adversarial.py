from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import unittest

from ..adapters.citrix_remote import CitrixObservation
from ..adapters.voice_intent import normalize_voice_intent
from ..contracts import (
    ActionKind,
    AdapterKind,
    ConfirmationTier,
    DecisionCode,
    EffectClass,
    LedgerStatus,
)
from ..policy import BrowserAutomationPolicy
from ..privacy_scan import scan
from ..run_validation import verify_contract_artifacts
from .common import (
    BASE_PRECONDITIONS,
    binding,
    candidate,
    confirmation,
    digest,
    geometry,
    grant,
    observation,
    proposal,
    target,
)


def execute_fixture_scenario(case_id: str) -> DecisionCode:
    policy = BrowserAutomationPolicy()
    if case_id == "B01":
        return policy.evaluate(grant(), proposal(), observation(), now_tick=100).code
    if case_id in {"B02", "G03"}:
        action = proposal(adapter=AdapterKind.RELATIVE_XY)
        return policy.evaluate(
            grant(),
            action,
            observation(candidate(node_id="node-a"), candidate(node_id="node-b")),
            now_tick=100,
        ).code
    if case_id == "B03":
        return policy.evaluate(
            grant(), proposal(), observation(candidate(attached=False)), now_tick=100
        ).code
    if case_id == "B04":
        return policy.evaluate(
            grant(), proposal(), observation(candidate(obscured=True)), now_tick=100
        ).code
    if case_id == "B05":
        return policy.evaluate(
            grant(), proposal(), observation(candidate(inert=True)), now_tick=100
        ).code
    if case_id == "B06":
        return policy.evaluate(
            grant(), proposal(), observation(candidate(enabled=False)), now_tick=100
        ).code
    if case_id == "B07":
        new_binding = binding(document_id="document-b", document_generation=5)
        return policy.evaluate(
            grant(),
            proposal(),
            observation(current_binding=new_binding),
            now_tick=100,
        ).code
    if case_id == "B08":
        action = proposal(action=ActionKind.NAVIGATE, effect=EffectClass.NAVIGATE)
        new_binding = binding(document_id="document-b", document_generation=5)
        return policy.evaluate(
            grant(),
            action,
            observation(current_binding=new_binding),
            now_tick=100,
            confirmation=confirmation(action, ConfirmationTier.USER_INTENT),
        ).code
    if case_id == "B09":
        frame_binding = binding(
            frame_ids=(0, 4),
            origin_ids=("origin-app", "origin-app"),
        )
        return policy.evaluate(
            grant(current_binding=frame_binding),
            proposal(current_binding=frame_binding),
            observation(
                candidate(current_binding=frame_binding),
                current_binding=frame_binding,
            ),
            now_tick=100,
        ).code
    if case_id == "B10":
        frame_binding = binding(
            frame_ids=(0, 4),
            origin_ids=("origin-app", "origin-frame"),
        )
        return policy.evaluate(
            grant(
                current_binding=frame_binding,
                allowed_chains=(("origin-app",),),
            ),
            proposal(current_binding=frame_binding),
            observation(
                candidate(current_binding=frame_binding),
                current_binding=frame_binding,
            ),
            now_tick=100,
        ).code
    if case_id in {"B11", "B12"}:
        shadow = "open" if case_id == "B11" else "closed"
        return policy.evaluate(
            grant(),
            proposal(),
            observation(candidate(shadow_root=shadow)),
            now_tick=100,
        ).code
    if case_id == "G01":
        action = proposal(adapter=AdapterKind.RELATIVE_XY)
        return policy.evaluate(
            grant(),
            action,
            observation(
                candidate(
                    semantic_available=False,
                    geometry_observation=geometry(),
                )
            ),
            now_tick=100,
        ).code
    if case_id == "G02":
        action = proposal(adapter=AdapterKind.RELATIVE_XY)
        drifted_target = replace(action.target, layout_generation=6)
        drifted_action = replace(
            action,
            proposal_id="proposal-fixture-drift",
            idempotency_key="idempotency-fixture-drift",
            target=drifted_target,
        )
        drift_grant = grant(
            allowed_action_targets=frozenset(
                {
                    (
                        drifted_action.adapter,
                        drifted_action.action,
                        drifted_action.effect,
                        drifted_target.kind,
                        drifted_target.contract_digest,
                    )
                }
            )
        )
        return policy.evaluate(
            drift_grant,
            drifted_action,
            observation(
                candidate(
                    semantic_available=False,
                    geometry_observation=geometry(),
                )
            ),
            now_tick=100,
        ).code
    if case_id == "G04":
        return policy.evaluate(
            grant(),
            proposal(adapter=AdapterKind.RELATIVE_XY),
            observation(
                candidate(
                    semantic_available=False,
                    geometry_observation=geometry(trained_regime_id=None),
                )
            ),
            now_tick=100,
        ).code
    if case_id in {"S01", "S02", "S03"}:
        return policy.evaluate(
            grant(),
            proposal(),
            observation(prompt_signals=(f"signal-{case_id.lower()}",)),
            now_tick=100,
        ).code
    if case_id == "S04":
        return policy.evaluate(
            grant(allowed_effects=frozenset({EffectClass.NAVIGATE})),
            proposal(),
            observation(),
            now_tick=100,
        ).code
    if case_id in {"L01", "L02", "L03"}:
        action = proposal()
        policy.evaluate(grant(), action, observation(), now_tick=100)
        if case_id == "L01":
            replay = action
        elif case_id == "L02":
            replay = replace(
                action,
                proposal_id="proposal-fixture-collision",
                payload_digest=digest("fixture-collision"),
            )
        else:
            policy.ledger.transition(
                action.idempotency_key,
                LedgerStatus.HANDED_OFF,
                LedgerStatus.INDETERMINATE,
            )
            replay = action
        return policy.evaluate(
            grant(), replay, observation(), now_tick=100
        ).code
    if case_id in {"C01", "C02", "C03"}:
        action = proposal(adapter=AdapterKind.CITRIX_REMOTE)
        remote = CitrixObservation(
            observation_id=f"fixture-{case_id.lower()}",
            local_window_id="citrix-window",
            remote_session_epoch=(
                "session-5" if case_id == "C01" else "session-4"
            ),
            control_epoch="control-9",
            trained_region_id="trained-region-a",
            frame_sequence=20,
            current_frame_sequence=20,
            geometry_generation=9 if case_id == "C03" else 8,
            expected_geometry_generation=8,
            focus_confirmed=True,
            frozen=case_id == "C02",
        )
        return policy.evaluate_citrix(
            grant(),
            action,
            remote,
            now_tick=100,
            confirmation=confirmation(action, ConfirmationTier.ACTION_BOUND),
        ).code
    if case_id == "V01":
        normalized = normalize_voice_intent(
            "draft and submit",
            {
                "draft": ("draft-intent", EffectClass.EDIT_DRAFT),
                "submit": ("submit-intent", EffectClass.EXTERNAL_SUBMIT),
            },
        )
        return (
            DecisionCode.INTENT_UNSUPPORTED
            if normalized.ambiguous
            else DecisionCode.HANDOFF_DENIED
        )
    if case_id == "V02":
        action = proposal(
            action=ActionKind.SUBMIT,
            effect=EffectClass.EXTERNAL_SUBMIT,
        )
        return policy.evaluate(
            grant(), action, observation(), now_tick=100
        ).code
    raise AssertionError(f"fixture scenario has no executable case: {case_id}")


class AdversarialPolicyTests(unittest.TestCase):
    def test_hidden_disabled_overlaid_and_unstable_targets_refuse(self) -> None:
        cases = (
            (candidate(visible=False), DecisionCode.TARGET_HIDDEN),
            (candidate(inert=True), DecisionCode.TARGET_HIDDEN),
            (candidate(enabled=False), DecisionCode.TARGET_DISABLED),
            (candidate(obscured=True), DecisionCode.TARGET_OBSCURED),
            (candidate(stable=False), DecisionCode.TARGET_UNSTABLE),
        )
        for item, code in cases:
            with self.subTest(code=code):
                decision = BrowserAutomationPolicy().evaluate(
                    grant(), proposal(), observation(item), now_tick=100
                )
                self.assertEqual(decision.code, code)

    def test_duplicate_contract_refuses_without_first_match_or_xy(self) -> None:
        first = candidate(node_id="node-a")
        second = candidate(node_id="node-b")
        action = proposal(adapter=AdapterKind.RELATIVE_XY)
        decision = BrowserAutomationPolicy().evaluate(
            grant(),
            action,
            observation(first, second),
            now_tick=100,
        )
        self.assertEqual(decision.code, DecisionCode.TARGET_AMBIGUOUS)

    def test_dynamic_replacement_and_document_commit_invalidate_handles(self) -> None:
        detached = candidate(attached=False)
        decision = BrowserAutomationPolicy().evaluate(
            grant(), proposal(), observation(detached), now_tick=100
        )
        self.assertEqual(decision.code, DecisionCode.STALE_HANDLE)

        new_binding = binding(document_id="document-b", document_generation=5)
        decision = BrowserAutomationPolicy().evaluate(
            grant(), proposal(), observation(current_binding=new_binding), now_tick=100
        )
        self.assertEqual(decision.code, DecisionCode.DOCUMENT_CHANGED)

    def test_navigation_race_invalidates_bound_confirmation(self) -> None:
        action = proposal(
            action=ActionKind.NAVIGATE,
            effect=EffectClass.NAVIGATE,
        )
        new_binding = binding(document_id="document-b", document_generation=5)
        decision = BrowserAutomationPolicy().evaluate(
            grant(),
            action,
            observation(current_binding=new_binding),
            now_tick=100,
            confirmation=confirmation(action, ConfirmationTier.USER_INTENT),
        )
        self.assertIn(
            decision.code,
            {DecisionCode.CONFIRMATION_STALE, DecisionCode.DOCUMENT_CHANGED},
        )

    def test_frame_chain_and_cross_origin_are_exact_allowlists(self) -> None:
        frame_binding = binding(
            frame_ids=(0, 4),
            origin_ids=("origin-app", "origin-frame"),
        )
        action = proposal(current_binding=frame_binding)
        blocked_grant = grant(
            current_binding=frame_binding,
            allowed_chains=(("origin-app",),),
        )
        decision = BrowserAutomationPolicy().evaluate(
            blocked_grant,
            action,
            observation(
                candidate(current_binding=frame_binding),
                current_binding=frame_binding,
            ),
            now_tick=100,
        )
        self.assertEqual(decision.code, DecisionCode.CROSS_ORIGIN_FRAME_BLOCKED)

        allowed_grant = grant(
            current_binding=frame_binding,
            allowed_chains=(("origin-app", "origin-frame"),),
        )
        decision = BrowserAutomationPolicy().evaluate(
            allowed_grant,
            action,
            observation(
                candidate(current_binding=frame_binding),
                current_binding=frame_binding,
            ),
            now_tick=100,
        )
        self.assertEqual(decision.code, DecisionCode.AUTHORIZED_HANDOFF)

        replaced_frame = binding(
            frame_ids=(0, 4),
            origin_ids=("origin-app", "origin-frame"),
            frame_document_ids=("document-a", "frame-document-new"),
            frame_generations=(4, 5),
        )
        decision = BrowserAutomationPolicy().evaluate(
            allowed_grant,
            action,
            observation(
                candidate(current_binding=replaced_frame),
                current_binding=replaced_frame,
            ),
            now_tick=100,
        )
        self.assertEqual(decision.code, DecisionCode.FRAME_CHANGED)

    def test_open_shadow_resolves_and_closed_shadow_refuses(self) -> None:
        open_result = BrowserAutomationPolicy().evaluate(
            grant(),
            proposal(),
            observation(candidate(shadow_root="open")),
            now_tick=100,
        )
        self.assertEqual(open_result.code, DecisionCode.AUTHORIZED_HANDOFF)

        closed_result = BrowserAutomationPolicy().evaluate(
            grant(),
            proposal(),
            observation(candidate(shadow_root="closed")),
            now_tick=100,
        )
        self.assertEqual(closed_result.code, DecisionCode.SHADOW_ROOT_CLOSED)

    def test_relative_xy_requires_semantic_identity_training_and_no_drift(self) -> None:
        action = proposal(adapter=AdapterKind.RELATIVE_XY)
        item = candidate(
            semantic_available=False,
            geometry_observation=geometry(),
        )
        allowed = BrowserAutomationPolicy().evaluate(
            grant(),
            action,
            observation(item),
            now_tick=100,
        )
        self.assertEqual(allowed.code, DecisionCode.AUTHORIZED_HANDOFF)
        self.assertEqual(allowed.handoff["targetKind"], "relative-region")
        self.assertEqual(
            allowed.handoff["targetContractDigest"],
            action.target.contract_digest,
        )
        self.assertEqual(allowed.handoff["relativeTrainedRegimeId"], "desktop-regime")
        self.assertEqual(allowed.handoff["relativeLayoutGeneration"], 5)

        drifted_target = replace(action.target, layout_generation=6)
        drifted_action = proposal(
            proposal_id="proposal-drift",
            idempotency_key="idempotency-drift",
            adapter=AdapterKind.RELATIVE_XY,
            target_contract=drifted_target,
        )
        drifted = BrowserAutomationPolicy().evaluate(
            grant(
                allowed_action_targets=frozenset(
                    {
                        (
                            drifted_action.adapter,
                            drifted_action.action,
                            drifted_action.effect,
                            drifted_action.target.kind,
                            drifted_action.target.contract_digest,
                        )
                    }
                )
            ),
            drifted_action,
            observation(item),
            now_tick=100,
        )
        self.assertEqual(drifted.code, DecisionCode.GEOMETRY_DRIFT)

    def test_relative_xy_never_bypasses_overlay_or_missing_training(self) -> None:
        action = proposal(adapter=AdapterKind.RELATIVE_XY)
        overlaid = candidate(
            semantic_available=False,
            obscured=True,
            geometry_observation=geometry(hit_contract_id="other-control"),
        )
        decision = BrowserAutomationPolicy().evaluate(
            grant(),
            action,
            observation(overlaid),
            now_tick=100,
        )
        self.assertEqual(decision.code, DecisionCode.TARGET_OBSCURED)

        untrained_action = proposal(
            proposal_id="proposal-untrained",
            idempotency_key="idempotency-untrained",
            adapter=AdapterKind.RELATIVE_XY,
        )
        untrained = candidate(
            semantic_available=False,
            geometry_observation=geometry(trained_regime_id=None),
        )
        decision = BrowserAutomationPolicy().evaluate(
            grant(),
            untrained_action,
            observation(untrained),
            now_tick=100,
        )
        self.assertEqual(decision.code, DecisionCode.GEOMETRY_UNTRAINED)

    def test_unknown_conditions_and_out_of_view_geometry_fail_at_boundary(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown precondition"):
            proposal(
                preconditions=BASE_PRECONDITIONS | {"page-command-authorized"}
            )
        with self.assertRaisesRegex(ValueError, "normalized viewport"):
            replace(geometry(), x_ratio=0.95, width_ratio=0.1)

    def test_action_replay_collision_and_indeterminate_outcome_refuse(self) -> None:
        action = proposal()
        policy = BrowserAutomationPolicy()
        first = policy.evaluate(grant(), action, observation(), now_tick=100)
        self.assertEqual(first.code, DecisionCode.AUTHORIZED_HANDOFF)
        replay = policy.evaluate(grant(), action, observation(), now_tick=100)
        self.assertEqual(replay.code, DecisionCode.ACTION_REPLAYED)

        collision = replace(
            action,
            proposal_id="proposal-collision",
            payload_digest=digest("different-proposal"),
        )
        decision = policy.evaluate(grant(), collision, observation(), now_tick=100)
        self.assertEqual(decision.code, DecisionCode.IDEMPOTENCY_COLLISION)

        other = proposal(
            proposal_id="proposal-uncertain",
            idempotency_key="idempotency-uncertain",
        )
        policy.evaluate(grant(), other, observation(), now_tick=100)
        policy.ledger.transition(
            other.idempotency_key,
            LedgerStatus.HANDED_OFF,
            LedgerStatus.INDETERMINATE,
        )
        decision = policy.evaluate(grant(), other, observation(), now_tick=100)
        self.assertEqual(decision.code, DecisionCode.PRIOR_OUTCOME_INDETERMINATE)

    def test_concurrent_replay_has_one_atomic_handoff(self) -> None:
        action = proposal()
        policy = BrowserAutomationPolicy()
        action_grant = grant()
        action_observation = observation()

        def evaluate_once(_: int) -> DecisionCode:
            return policy.evaluate(
                action_grant,
                action,
                action_observation,
                now_tick=100,
            ).code

        with ThreadPoolExecutor(max_workers=8) as executor:
            codes = list(executor.map(evaluate_once, range(32)))
        self.assertEqual(codes.count(DecisionCode.AUTHORIZED_HANDOFF), 1)
        self.assertEqual(codes.count(DecisionCode.ACTION_REPLAYED), 31)

    def test_citrix_is_separate_and_checks_session_focus_frame_and_geometry(self) -> None:
        action = proposal(adapter=AdapterKind.CITRIX_REMOTE)
        confirmed = confirmation(action, ConfirmationTier.ACTION_BOUND)
        base = CitrixObservation(
            observation_id="citrix-observation",
            local_window_id="citrix-window",
            remote_session_epoch="session-4",
            control_epoch="control-9",
            trained_region_id="trained-region-a",
            frame_sequence=20,
            current_frame_sequence=20,
            geometry_generation=8,
            expected_geometry_generation=8,
            focus_confirmed=True,
            frozen=False,
        )
        allowed = BrowserAutomationPolicy().evaluate_citrix(
            grant(),
            action,
            base,
            now_tick=100,
            confirmation=confirmed,
        )
        self.assertEqual(allowed.code, DecisionCode.AUTHORIZED_HANDOFF)
        self.assertEqual(allowed.handoff["targetKind"], "remote-region")
        self.assertEqual(allowed.handoff["localWindowId"], "citrix-window")
        self.assertEqual(allowed.handoff["remoteSessionEpoch"], "session-4")
        self.assertEqual(allowed.handoff["controlEpoch"], "control-9")
        self.assertEqual(allowed.handoff["remoteGeometryGeneration"], 8)
        changed_target = replace(action.target, control_epoch="control-10")
        self.assertNotEqual(
            action.proposal_digest,
            replace(action, target=changed_target).proposal_digest,
        )

        cases = (
            (
                replace(base, remote_session_epoch="session-5"),
                DecisionCode.REMOTE_SESSION_CHANGED,
            ),
            (replace(base, frozen=True), DecisionCode.REMOTE_FRAME_STALE),
            (
                replace(base, geometry_generation=9),
                DecisionCode.GEOMETRY_DRIFT,
            ),
        )
        for index, (item, code) in enumerate(cases):
            with self.subTest(code=code):
                action_case = proposal(
                    proposal_id=f"proposal-citrix-{index}",
                    idempotency_key=f"idempotency-citrix-{index}",
                    adapter=AdapterKind.CITRIX_REMOTE,
                )
                decision = BrowserAutomationPolicy().evaluate_citrix(
                    grant(),
                    action_case,
                    item,
                    now_tick=100,
                    confirmation=confirmation(
                        action_case, ConfirmationTier.ACTION_BOUND
                    ),
                )
                self.assertEqual(decision.code, code)

        swapped_action = proposal(
            proposal_id="proposal-adapter-swap",
            idempotency_key="idempotency-adapter-swap",
            adapter=AdapterKind.CITRIX_REMOTE,
            target_contract=replace(action.target, region_contract_id="save-control"),
        )
        semantic_target = target()
        semantic_only = grant(
            allowed_action_targets=frozenset(
                {
                    (
                        AdapterKind.SEMANTIC_DOM,
                        ActionKind.OBSERVE,
                        EffectClass.OBSERVE,
                        semantic_target.kind,
                        semantic_target.contract_digest,
                    )
                }
            )
        )
        refused = BrowserAutomationPolicy().evaluate_citrix(
            semantic_only,
            swapped_action,
            base,
            now_tick=100,
            confirmation=confirmation(
                swapped_action, ConfirmationTier.ACTION_BOUND
            ),
        )
        self.assertEqual(refused.code, DecisionCode.TARGET_NOT_ALLOWED)

    def test_voice_normalizes_intent_only_and_preserves_ambiguity(self) -> None:
        catalog = {
            "draft": ("draft-intent", EffectClass.EDIT_DRAFT),
            "submit": ("submit-intent", EffectClass.EXTERNAL_SUBMIT),
        }
        draft = normalize_voice_intent("Please draft this", catalog)
        self.assertEqual(draft.intent_id, "draft-intent")
        self.assertFalse(draft.ambiguous)
        self.assertFalse(hasattr(draft, "selector"))
        self.assertFalse(hasattr(draft, "coordinate"))

        ambiguous = normalize_voice_intent("draft and submit", catalog)
        self.assertTrue(ambiguous.ambiguous)
        self.assertEqual(ambiguous.intent_id, "ambiguous-intent")

    def test_fixture_contract_schema_and_static_privacy_gates(self) -> None:
        verify_contract_artifacts()
        self.assertEqual(scan(), [])
        fixture_path = (
            Path(__file__).resolve().parents[1]
            / "fixtures"
            / "adversarial-scenarios.synthetic.json"
        )
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(fixture["scenarios"]), 25)
        self.assertTrue(all(case["expectedEffects"] == 0 for case in fixture["scenarios"]))
        self.assertEqual(
            set(fixture["coverage"]),
            {case["id"] for case in fixture["scenarios"]},
        )
        for case in fixture["scenarios"]:
            with self.subTest(case_id=case["id"]):
                self.assertEqual(
                    execute_fixture_scenario(case["id"]).value,
                    case["expectedCode"],
                )


if __name__ == "__main__":
    unittest.main()
