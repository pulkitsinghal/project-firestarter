"""Bounded Relative XY fallback for a previously identified semantic target."""

from __future__ import annotations

from typing import Optional

from ..contracts import DecisionCode, ElementCandidate, RelativeTargetContract


def validate_geometry(
    candidate: ElementCandidate,
    target: RelativeTargetContract,
) -> Optional[DecisionCode]:
    geometry = candidate.geometry
    if candidate.semantic_available:
        return DecisionCode.GEOMETRY_NOT_ALLOWED
    if geometry is None:
        return DecisionCode.GEOMETRY_UNTRAINED
    if (
        geometry.trained_regime_id is None
        or geometry.trained_regime_id != target.trained_regime_id
    ):
        return DecisionCode.GEOMETRY_UNTRAINED
    if (
        geometry.viewport_generation != target.viewport_generation
        or geometry.layout_generation != target.layout_generation
        or geometry.transform_generation != target.transform_generation
        or geometry.x_ratio != target.x_ratio
        or geometry.y_ratio != target.y_ratio
        or geometry.width_ratio != target.width_ratio
        or geometry.height_ratio != target.height_ratio
    ):
        return DecisionCode.GEOMETRY_DRIFT
    if candidate.obscured or geometry.hit_contract_id != candidate.contract_id:
        return DecisionCode.TARGET_OBSCURED
    if not candidate.attached:
        return DecisionCode.STALE_HANDLE
    if not candidate.visible or candidate.inert:
        return DecisionCode.TARGET_HIDDEN
    if not candidate.enabled:
        return DecisionCode.TARGET_DISABLED
    if not candidate.stable:
        return DecisionCode.TARGET_UNSTABLE
    return None
