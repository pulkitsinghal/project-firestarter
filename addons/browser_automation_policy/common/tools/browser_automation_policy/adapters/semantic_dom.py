"""Semantic accessibility/DOM locator contract."""

from __future__ import annotations

from typing import Optional, Tuple

from ..contracts import (
    DecisionCode,
    DocumentBinding,
    ElementCandidate,
    RelativeTargetContract,
    SemanticObservation,
    TargetContract,
)


def _same_binding(left: DocumentBinding, right: DocumentBinding) -> Optional[DecisionCode]:
    if left.tab_id != right.tab_id:
        return DecisionCode.STALE_HANDLE
    if left.document_id != right.document_id:
        return DecisionCode.DOCUMENT_CHANGED
    if (
        left.frame_ids != right.frame_ids
        or left.frame_document_ids != right.frame_document_ids
        or left.frame_generations != right.frame_generations
    ):
        return DecisionCode.FRAME_CHANGED
    if left.origin_ids != right.origin_ids:
        return DecisionCode.ORIGIN_NOT_ALLOWED
    if (
        left.document_generation != right.document_generation
        or left.surface_generation != right.surface_generation
        or left.adapter_version != right.adapter_version
    ):
        return DecisionCode.STALE_HANDLE
    return None


def resolve_semantic(
    target: TargetContract | RelativeTargetContract,
    expected_binding: DocumentBinding,
    observation: SemanticObservation,
) -> Tuple[Optional[ElementCandidate], Optional[DecisionCode]]:
    stale = _same_binding(expected_binding, observation.binding)
    if stale is not None:
        return None, stale

    matches = tuple(
        candidate
        for candidate in observation.candidates
        if candidate.contract_id == target.contract_id
        and candidate.role == target.role
        and candidate.accessible_name_token == target.accessible_name_token
        and candidate.container_contract_id == target.container_contract_id
    )
    if not matches:
        return None, DecisionCode.TARGET_NOT_FOUND
    if len(matches) != 1:
        return None, DecisionCode.TARGET_AMBIGUOUS

    candidate = matches[0]
    stale = _same_binding(expected_binding, candidate.binding)
    if stale is not None:
        return None, stale
    if candidate.shadow_root == "closed":
        return None, DecisionCode.SHADOW_ROOT_CLOSED
    if not candidate.semantic_available:
        return candidate, DecisionCode.SEMANTIC_REQUIRED
    if not candidate.attached:
        return None, DecisionCode.STALE_HANDLE
    if not candidate.visible or candidate.inert:
        return None, DecisionCode.TARGET_HIDDEN
    if not candidate.enabled:
        return None, DecisionCode.TARGET_DISABLED
    if not candidate.stable:
        return None, DecisionCode.TARGET_UNSTABLE
    if candidate.obscured:
        return None, DecisionCode.TARGET_OBSCURED
    return candidate, None
