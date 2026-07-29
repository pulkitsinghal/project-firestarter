"""Separate remote-surface contract; remote pixels never become DOM semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..contracts import DecisionCode, RemoteTargetContract, require_id


@dataclass(frozen=True, slots=True)
class CitrixObservation:
    observation_id: str
    local_window_id: str
    remote_session_epoch: str
    control_epoch: str
    trained_region_id: Optional[str]
    frame_sequence: int
    current_frame_sequence: int
    geometry_generation: int
    expected_geometry_generation: int
    focus_confirmed: bool
    frozen: bool

    def __post_init__(self) -> None:
        for field, value in (
            ("observation_id", self.observation_id),
            ("local_window_id", self.local_window_id),
            ("remote_session_epoch", self.remote_session_epoch),
            ("control_epoch", self.control_epoch),
        ):
            require_id(value, field)
        if self.trained_region_id is not None:
            require_id(self.trained_region_id, "trained_region_id")
        if min(
            self.frame_sequence,
            self.current_frame_sequence,
            self.geometry_generation,
            self.expected_geometry_generation,
        ) < 0:
            raise ValueError("remote sequence and geometry values must be non-negative")


def validate_citrix(
    observation: CitrixObservation,
    target: RemoteTargetContract,
) -> Optional[DecisionCode]:
    if (
        observation.local_window_id != target.local_window_id
        or observation.remote_session_epoch != target.remote_session_epoch
        or observation.control_epoch != target.control_epoch
    ):
        return DecisionCode.REMOTE_SESSION_CHANGED
    if (
        observation.frozen
        or observation.frame_sequence < observation.current_frame_sequence
    ):
        return DecisionCode.REMOTE_FRAME_STALE
    if not observation.focus_confirmed:
        return DecisionCode.PRECONDITION_FAILED
    if (
        observation.trained_region_id is None
        or observation.trained_region_id != target.trained_region_id
    ):
        return DecisionCode.GEOMETRY_UNTRAINED
    if (
        observation.geometry_generation != observation.expected_geometry_generation
        or observation.geometry_generation != target.geometry_generation
    ):
        return DecisionCode.GEOMETRY_DRIFT
    return None
