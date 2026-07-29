from __future__ import annotations

from dataclasses import replace
import hashlib

from ..contracts import (
    ActionKind,
    ActionProposal,
    AdapterKind,
    CapabilityGrant,
    Confirmation,
    ConfirmationTier,
    DocumentBinding,
    EffectClass,
    ElementCandidate,
    GeometryObservation,
    RelativeTargetContract,
    Reversibility,
    RemoteTargetContract,
    SemanticObservation,
    TargetContract,
)


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


def digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def binding(
    *,
    document_id: str = "document-a",
    frame_ids: tuple[int, ...] = (0,),
    origin_ids: tuple[str, ...] = ("origin-app",),
    frame_document_ids: tuple[str, ...] | None = None,
    frame_generations: tuple[int, ...] | None = None,
    document_generation: int = 4,
    surface_generation: int = 9,
) -> DocumentBinding:
    if frame_document_ids is None:
        frame_document_ids = (document_id,) + tuple(
            f"frame-document-{frame_id}" for frame_id in frame_ids[1:]
        )
    if frame_generations is None:
        frame_generations = tuple(document_generation for _ in frame_ids)
    return DocumentBinding(
        tab_id=7,
        document_id=document_id,
        frame_ids=frame_ids,
        origin_ids=origin_ids,
        frame_document_ids=frame_document_ids,
        frame_generations=frame_generations,
        document_generation=document_generation,
        surface_generation=surface_generation,
        adapter_version="semantic-1.0",
    )


def grant(
    *,
    current_binding: DocumentBinding | None = None,
    allowed_adapters: frozenset[AdapterKind] | None = None,
    allowed_effects: frozenset[EffectClass] | None = None,
    allowed_chains: tuple[tuple[str, ...], ...] | None = None,
    allowed_action_targets: frozenset[
        tuple[AdapterKind, ActionKind, EffectClass, str, str]
    ] | None = None,
    allow_geometry_fallback: bool = True,
) -> CapabilityGrant:
    current_binding = current_binding or binding()
    if allowed_action_targets is None:
        action_effects = (
            (ActionKind.OBSERVE, EffectClass.OBSERVE),
            (ActionKind.FOCUS, EffectClass.OBSERVE),
            (ActionKind.ACTIVATE, EffectClass.NAVIGATE),
            (ActionKind.NAVIGATE, EffectClass.NAVIGATE),
            (ActionKind.SET_VALUE, EffectClass.EDIT_DRAFT),
            (ActionKind.CLEAR_VALUE, EffectClass.EDIT_DRAFT),
            (ActionKind.SELECT, EffectClass.EDIT_DRAFT),
            (ActionKind.EXTERNAL_SEND, EffectClass.EXTERNAL_SUBMIT),
            (ActionKind.SUBMIT, EffectClass.EXTERNAL_SUBMIT),
            (ActionKind.UPLOAD, EffectClass.EXTERNAL_SUBMIT),
            (ActionKind.DELETE, EffectClass.DESTRUCTIVE),
            (ActionKind.GRANT_PERMISSION, EffectClass.DESTRUCTIVE),
        )
        targets = (
            (AdapterKind.SEMANTIC_DOM, target()),
            (AdapterKind.RELATIVE_XY, relative_target()),
            (
                AdapterKind.CITRIX_REMOTE,
                RemoteTargetContract(
                    region_contract_id="remote-region-a",
                    local_window_id="citrix-window",
                    remote_session_epoch="session-4",
                    control_epoch="control-9",
                    trained_region_id="trained-region-a",
                    geometry_generation=8,
                ),
            ),
        )
        allowed_action_targets = frozenset(
            (
                adapter,
                action,
                effect,
                target_contract.kind,
                target_contract.contract_digest,
            )
            for adapter, target_contract in targets
            for action, effect in action_effects
        )
    return CapabilityGrant(
        grant_id="grant-a",
        task_id="task-a",
        allowed_origin_ids=frozenset(current_binding.origin_ids),
        allowed_frame_origin_chains=allowed_chains
        or (current_binding.origin_ids,),
        allowed_adapters=allowed_adapters
        or frozenset(
            {
                AdapterKind.SEMANTIC_DOM,
                AdapterKind.RELATIVE_XY,
                AdapterKind.CITRIX_REMOTE,
            }
        ),
        allowed_effects=allowed_effects
        or frozenset(
            {
                EffectClass.OBSERVE,
                EffectClass.NAVIGATE,
                EffectClass.EDIT_DRAFT,
                EffectClass.EXTERNAL_SUBMIT,
                EffectClass.DESTRUCTIVE,
            }
        ),
        allowed_action_targets=allowed_action_targets,
        expires_at_tick=1_000,
        allow_geometry_fallback=allow_geometry_fallback,
    )


def target() -> TargetContract:
    return TargetContract(
        contract_id="save-control",
        role="button",
        accessible_name_token="save-draft",
        container_contract_id="editor-panel",
    )


def relative_target() -> RelativeTargetContract:
    return RelativeTargetContract(
        contract_id="save-control",
        role="button",
        accessible_name_token="save-draft",
        container_contract_id="editor-panel",
        trained_regime_id="desktop-regime",
        x_ratio=0.75,
        y_ratio=0.6,
        width_ratio=0.1,
        height_ratio=0.05,
        viewport_generation=3,
        layout_generation=5,
        transform_generation=8,
    )


def proposal(
    *,
    proposal_id: str = "proposal-a",
    idempotency_key: str = "idempotency-a",
    action: ActionKind = ActionKind.OBSERVE,
    effect: EffectClass = EffectClass.OBSERVE,
    adapter: AdapterKind = AdapterKind.SEMANTIC_DOM,
    current_binding: DocumentBinding | None = None,
    preconditions: frozenset[str] | None = None,
    postconditions: frozenset[str] | None = None,
    reversibility: Reversibility | None = None,
    reversal_action: ActionKind | None = None,
    reversal_payload_digest: str | None = None,
    target_contract: (
        TargetContract | RelativeTargetContract | RemoteTargetContract | None
    ) = None,
) -> ActionProposal:
    current_binding = current_binding or binding()
    if preconditions is None:
        preconditions = BASE_PRECONDITIONS
        if action in {
            ActionKind.SET_VALUE,
            ActionKind.CLEAR_VALUE,
            ActionKind.SELECT,
            ActionKind.EXTERNAL_SEND,
            ActionKind.SUBMIT,
            ActionKind.UPLOAD,
        }:
            preconditions = preconditions | {"focus-current"}
    if postconditions is None:
        postconditions = frozenset(
            {
                {
                    EffectClass.OBSERVE: "state-observed",
                    EffectClass.NAVIGATE: "navigation-reconciled",
                    EffectClass.EDIT_DRAFT: "draft-reconciled",
                    EffectClass.EXTERNAL_SUBMIT: "external-effect-reconciled",
                    EffectClass.DESTRUCTIVE: "destructive-effect-reconciled",
                }[effect]
            }
        )
    if reversibility is None:
        reversibility = {
            EffectClass.OBSERVE: Reversibility.READ_ONLY,
            EffectClass.NAVIGATE: Reversibility.COMPENSATING,
            EffectClass.EDIT_DRAFT: Reversibility.REVERSIBLE,
            EffectClass.EXTERNAL_SUBMIT: Reversibility.IRREVERSIBLE,
            EffectClass.DESTRUCTIVE: Reversibility.IRREVERSIBLE,
        }[effect]
    if effect is EffectClass.EDIT_DRAFT and reversal_action is None:
        reversal_action = ActionKind.CLEAR_VALUE
    if effect is EffectClass.EDIT_DRAFT and reversal_payload_digest is None:
        reversal_payload_digest = digest(f"reversal-{proposal_id}")
    if target_contract is None:
        if adapter is AdapterKind.CITRIX_REMOTE:
            target_contract = RemoteTargetContract(
                region_contract_id="remote-region-a",
                local_window_id="citrix-window",
                remote_session_epoch="session-4",
                control_epoch="control-9",
                trained_region_id="trained-region-a",
                geometry_generation=8,
            )
        elif adapter is AdapterKind.RELATIVE_XY:
            target_contract = relative_target()
        else:
            target_contract = target()
    return ActionProposal(
        proposal_id=proposal_id,
        idempotency_key=idempotency_key,
        task_id="task-a",
        action=action,
        effect=effect,
        adapter=adapter,
        binding=current_binding,
        target=target_contract,
        payload_digest=digest(f"payload-{proposal_id}"),
        preconditions=preconditions,
        postconditions=postconditions,
        reversibility=reversibility,
        reversal_action=reversal_action,
        reversal_payload_digest=reversal_payload_digest,
        expires_at_tick=500,
    )


def geometry(
    *,
    viewport_generation: int = 3,
    layout_generation: int = 5,
    transform_generation: int = 8,
    trained_regime_id: str | None = "desktop-regime",
    hit_contract_id: str | None = "save-control",
) -> GeometryObservation:
    return GeometryObservation(
        x_ratio=0.75,
        y_ratio=0.6,
        width_ratio=0.1,
        height_ratio=0.05,
        viewport_generation=viewport_generation,
        layout_generation=layout_generation,
        transform_generation=transform_generation,
        trained_regime_id=trained_regime_id,
        hit_contract_id=hit_contract_id,
    )


def candidate(
    *,
    current_binding: DocumentBinding | None = None,
    node_id: str = "node-a",
    semantic_available: bool = True,
    shadow_root: str = "none",
    geometry_observation: GeometryObservation | None = None,
    **changes: object,
) -> ElementCandidate:
    item = ElementCandidate(
        node_id=node_id,
        contract_id="save-control",
        role="button",
        accessible_name_token="save-draft",
        container_contract_id="editor-panel",
        binding=current_binding or binding(),
        semantic_available=semantic_available,
        shadow_root=shadow_root,
        geometry=geometry_observation,
    )
    return replace(item, **changes)


def observation(
    *items: ElementCandidate,
    current_binding: DocumentBinding | None = None,
    focus_confirmed: bool = True,
    prompt_signals: tuple[str, ...] = (),
) -> SemanticObservation:
    current_binding = current_binding or binding()
    if not items:
        items = (candidate(current_binding=current_binding),)
    return SemanticObservation(
        observation_id="observation-a",
        binding=current_binding,
        candidates=tuple(items),
        focus_confirmed=focus_confirmed,
        prompt_injection_signal_ids=prompt_signals,
    )


def confirmation(
    action_proposal: ActionProposal,
    tier: ConfirmationTier,
    *,
    expires_at_tick: int = 400,
    **changes: object,
) -> Confirmation:
    item = Confirmation(
        confirmation_id=f"confirm-{action_proposal.proposal_id}",
        proposal_id=action_proposal.proposal_id,
        proposal_digest=action_proposal.proposal_digest,
        payload_digest=action_proposal.payload_digest,
        document_id=action_proposal.binding.document_id,
        document_generation=action_proposal.binding.document_generation,
        surface_generation=action_proposal.binding.surface_generation,
        tier=tier,
        expires_at_tick=expires_at_tick,
    )
    return replace(item, **changes)
