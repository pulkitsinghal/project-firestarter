"""Privacy-safe evidence and future-executor handoff envelopes."""

from __future__ import annotations

import hashlib
from typing import Any, Dict

from .contracts import (
    ActionProposal,
    ConfirmationTier,
    Decision,
    DocumentBinding,
    RelativeTargetContract,
    RemoteTargetContract,
)


EVIDENCE_KEYS = frozenset(
    {
        "schemaVersion",
        "policyVersion",
        "decisionCode",
        "allowed",
        "proposalId",
        "adapter",
        "documentGeneration",
        "surfaceGeneration",
        "frameDepth",
        "confirmationTier",
    }
)

FORBIDDEN_KEY_PARTS = (
    "url",
    "uri",
    "origin",
    "host",
    "path",
    "query",
    "text",
    "prompt",
    "selector",
    "value",
    "cookie",
    "token",
    "credential",
    "email",
    "screenshot",
    "ocr",
    "coordinate",
)


def evidence_envelope(decision: Decision, binding: DocumentBinding) -> Dict[str, Any]:
    envelope: Dict[str, Any] = {
        "schemaVersion": "1.0",
        "policyVersion": "0.1.0",
        "decisionCode": decision.code.value,
        "allowed": decision.allowed,
        "proposalId": decision.proposal_id,
        "adapter": decision.adapter.value,
        "documentGeneration": binding.document_generation,
        "surfaceGeneration": binding.surface_generation,
        "frameDepth": len(binding.frame_ids),
        "confirmationTier": int(decision.required_confirmation),
    }
    assert_minimized_envelope(envelope)
    return envelope


def assert_minimized_envelope(envelope: Dict[str, Any]) -> None:
    unknown = set(envelope) - EVIDENCE_KEYS
    if unknown:
        raise ValueError(f"evidence contains unknown keys: {sorted(unknown)}")
    for key in envelope:
        lowered = key.lower()
        if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
            raise ValueError(f"evidence key is privacy-forbidden: {key}")
    encoded = repr(envelope)
    if len(encoded) > 1_024:
        raise ValueError("evidence envelope exceeds size bound")


def future_executor_handoff(
    proposal: ActionProposal,
    *,
    grant_id: str,
    grant_expires_at_tick: int,
    confirmation_tier: ConfirmationTier,
    issued_at_tick: int,
    expires_at_tick: int,
) -> Dict[str, Any]:
    """Build a content-free handoff. This is authorization, not execution."""

    if expires_at_tick <= issued_at_tick:
        raise ValueError("handoff expiry must be after issuance")
    if expires_at_tick > min(
        proposal.expires_at_tick,
        grant_expires_at_tick,
        issued_at_tick + 60,
    ):
        raise ValueError("handoff must be short-lived and grant/proposal-bounded")
    handoff_nonce = "sha256:" + hashlib.sha256(
        (
            f"{proposal.idempotency_key}:{proposal.proposal_digest}:"
            f"{grant_id}:{issued_at_tick}:{expires_at_tick}"
        ).encode("utf-8")
    ).hexdigest()
    remote_target = (
        proposal.target
        if isinstance(proposal.target, RemoteTargetContract)
        else None
    )
    relative_target = (
        proposal.target
        if isinstance(proposal.target, RelativeTargetContract)
        else None
    )
    return {
        "schemaVersion": "1.0",
        "kind": "future-executor-handoff",
        "policyVersion": "0.1.0",
        "proposalId": proposal.proposal_id,
        "idempotencyKey": proposal.idempotency_key,
        "handoffNonce": handoff_nonce,
        "proposalDigest": proposal.proposal_digest,
        "payloadDigest": proposal.payload_digest,
        "grantId": grant_id,
        "taskId": proposal.task_id,
        "adapter": proposal.adapter.value,
        "action": proposal.action.value,
        "effect": proposal.effect.value,
        "targetKind": proposal.target.kind,
        "targetContractId": proposal.target.target_contract_id,
        "targetContractDigest": proposal.target.contract_digest,
        "relativeTrainedRegimeId": (
            relative_target.trained_regime_id
            if relative_target is not None
            else None
        ),
        "relativeXRatio": (
            relative_target.x_ratio if relative_target is not None else None
        ),
        "relativeYRatio": (
            relative_target.y_ratio if relative_target is not None else None
        ),
        "relativeWidthRatio": (
            relative_target.width_ratio if relative_target is not None else None
        ),
        "relativeHeightRatio": (
            relative_target.height_ratio if relative_target is not None else None
        ),
        "relativeViewportGeneration": (
            relative_target.viewport_generation
            if relative_target is not None
            else None
        ),
        "relativeLayoutGeneration": (
            relative_target.layout_generation
            if relative_target is not None
            else None
        ),
        "relativeTransformGeneration": (
            relative_target.transform_generation
            if relative_target is not None
            else None
        ),
        "localWindowId": (
            remote_target.local_window_id if remote_target is not None else None
        ),
        "remoteSessionEpoch": (
            remote_target.remote_session_epoch if remote_target is not None else None
        ),
        "controlEpoch": (
            remote_target.control_epoch if remote_target is not None else None
        ),
        "trainedRegionId": (
            remote_target.trained_region_id if remote_target is not None else None
        ),
        "remoteGeometryGeneration": (
            remote_target.geometry_generation if remote_target is not None else None
        ),
        "tabId": proposal.binding.tab_id,
        "documentId": proposal.binding.document_id,
        "frameIds": list(proposal.binding.frame_ids),
        "frameDocumentIds": list(proposal.binding.frame_document_ids),
        "frameGenerations": list(proposal.binding.frame_generations),
        "originIds": list(proposal.binding.origin_ids),
        "documentGeneration": proposal.binding.document_generation,
        "surfaceGeneration": proposal.binding.surface_generation,
        "adapterVersion": proposal.binding.adapter_version,
        "preconditions": sorted(proposal.preconditions),
        "postconditions": sorted(proposal.postconditions),
        "confirmationTier": int(confirmation_tier),
        "reversibility": proposal.reversibility.value,
        "reversalAction": (
            proposal.reversal_action.value
            if proposal.reversal_action is not None
            else None
        ),
        "reversalPayloadDigest": proposal.reversal_payload_digest,
        "issuedAtTick": issued_at_tick,
        "expiresAtTick": expires_at_tick,
        "executorConfigured": False,
    }
