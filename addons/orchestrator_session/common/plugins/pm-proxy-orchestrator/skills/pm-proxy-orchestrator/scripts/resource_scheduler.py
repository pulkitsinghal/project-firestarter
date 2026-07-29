#!/usr/bin/env python3
"""Privacy-safe logical-lane and host-contention scheduling primitive."""

from __future__ import annotations

from typing import Any


RESOURCE_CLASSES = {"light", "heavy"}
INTENSITIES = {"low", "moderate", "high"}


def _profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "resource_class",
        "contention_group",
        "cpu_intensity",
        "memory_intensity",
        "io_intensity",
    }:
        raise ValueError("resource_profile fields are incompatible")
    if value["resource_class"] not in RESOURCE_CLASSES:
        raise ValueError("resource_class is invalid")
    group = value["contention_group"]
    if (
        not isinstance(group, str)
        or not group
        or len(group) > 64
        or "/" in group
        or "\\" in group
        or "@" in group
    ):
        raise ValueError("contention_group must be a coarse privacy-safe alias")
    for key in ("cpu_intensity", "memory_intensity", "io_intensity"):
        if value[key] not in INTENSITIES:
            raise ValueError(f"{key} is invalid")
    return dict(value)


def schedule(
    *,
    configured_lane_capacity: int,
    active_or_reserved: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Select candidates without treating logical lanes as CPU processes."""

    if (
        not isinstance(configured_lane_capacity, int)
        or isinstance(configured_lane_capacity, bool)
        or not 1 <= configured_lane_capacity <= 64
    ):
        raise ValueError("configured_lane_capacity must be 1..64")
    active_heavy_groups = {
        _profile(item["resource_profile"])["contention_group"]
        for item in active_or_reserved
        if _profile(item["resource_profile"])["resource_class"] == "heavy"
    }
    deficit = max(0, configured_lane_capacity - len(active_or_reserved))
    selected: list[str] = []
    deferred: list[dict[str, str]] = []
    ordered = sorted(
        candidates,
        key=lambda item: (
            -int(item["priority"]),
            -int(item["queue_seconds"]),
            str(item["candidate_id"]),
        ),
    )
    for candidate in ordered:
        profile = _profile(candidate["resource_profile"])
        if len(selected) >= deficit:
            deferred.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "reason_code": "LOGICAL_CAPACITY_FULL",
                }
            )
            continue
        if (
            profile["resource_class"] == "heavy"
            and profile["contention_group"] in active_heavy_groups
        ):
            deferred.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "reason_code": "HEAVY_CONTENTION_SERIALIZED",
                }
            )
            continue
        selected.append(candidate["candidate_id"])
        if profile["resource_class"] == "heavy":
            active_heavy_groups.add(profile["contention_group"])
    return {
        "configured_lane_capacity": configured_lane_capacity,
        "active_or_reserved_count": len(active_or_reserved),
        "logical_lane_deficit": deficit,
        "selected_candidate_ids": selected,
        "deferred": deferred,
        "process_oversubscription_inferred": False,
    }
