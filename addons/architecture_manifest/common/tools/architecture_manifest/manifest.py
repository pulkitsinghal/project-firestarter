"""Deterministic, fail-closed loader/validator for a manifest instance.

``load_manifest`` accepts a plain ``dict`` (already parsed from JSON) and returns
an :class:`ArchitectureManifest`, or raises :class:`ManifestError` with a closed
:class:`ManifestErrorCode`. It never mutates its input, never touches the
network or filesystem, and produces a stable canonical projection regardless of
the ordering of the input lists.
"""

from __future__ import annotations

from typing import Tuple

from .contracts import (
    ArchitectureManifest,
    Component,
    ComponentKind,
    DataClass,
    DataStore,
    DataStoreKind,
    Dependency,
    DependencyKind,
    ManifestError,
    ManifestErrorCode,
    OwnerRole,
    SCHEMA_VERSION,
    TrustBoundary,
    TrustTier,
    _enum,
    _parse_evidence,
)


_TOP_LEVEL_REQUIRED = {
    "schemaVersion",
    "manifestId",
    "trustBoundaries",
    "components",
    "dataStores",
    "dependencies",
}

_BOUNDARY_KEYS = {"boundaryId", "name", "tier"}
_COMPONENT_KEYS = {
    "componentId",
    "name",
    "kind",
    "boundaryId",
    "ownerRole",
    "ownerToken",
    "evidence",
}
_STORE_KEYS = {
    "storeId",
    "name",
    "kind",
    "boundaryId",
    "ownerRole",
    "ownerToken",
    "dataClass",
    "evidence",
}
_DEPENDENCY_KEYS = {
    "dependencyId",
    "source",
    "target",
    "relation",
    "dataClass",
    "evidence",
}


def _require_object(value: object, field: str) -> dict:
    if not isinstance(value, dict):
        raise ManifestError(ManifestErrorCode.MISSING_FIELD, f"{field} must be an object")
    return value


def _require_list(value: object, field: str) -> list:
    if not isinstance(value, list):
        raise ManifestError(ManifestErrorCode.MISSING_FIELD, f"{field} must be a list")
    return value


def _check_keys(entry: dict, allowed: set, field: str) -> None:
    keys = set(entry)
    if not keys <= allowed:
        raise ManifestError(
            ManifestErrorCode.UNKNOWN_FIELD, f"{field} has unknown fields"
        )
    if not allowed <= keys:
        raise ManifestError(
            ManifestErrorCode.MISSING_FIELD, f"{field} is missing required fields"
        )


def _parse_boundary(entry: object) -> TrustBoundary:
    entry = _require_object(entry, "trustBoundary")
    _check_keys(entry, _BOUNDARY_KEYS, "trustBoundary")
    return TrustBoundary(
        boundary_id=entry["boundaryId"],
        name=entry["name"],
        tier=_enum(TrustTier, entry["tier"], "trustBoundary.tier"),
    )


def _parse_component(entry: object) -> Component:
    entry = _require_object(entry, "component")
    _check_keys(entry, _COMPONENT_KEYS, "component")
    return Component(
        component_id=entry["componentId"],
        name=entry["name"],
        kind=_enum(ComponentKind, entry["kind"], "component.kind"),
        boundary_id=entry["boundaryId"],
        owner_role=_enum(OwnerRole, entry["ownerRole"], "component.ownerRole"),
        owner_token=entry["ownerToken"],
        evidence=_parse_evidence(entry["evidence"], "component.evidence"),
    )


def _parse_store(entry: object) -> DataStore:
    entry = _require_object(entry, "dataStore")
    _check_keys(entry, _STORE_KEYS, "dataStore")
    return DataStore(
        store_id=entry["storeId"],
        name=entry["name"],
        kind=_enum(DataStoreKind, entry["kind"], "dataStore.kind"),
        boundary_id=entry["boundaryId"],
        owner_role=_enum(OwnerRole, entry["ownerRole"], "dataStore.ownerRole"),
        owner_token=entry["ownerToken"],
        data_class=_enum(DataClass, entry["dataClass"], "dataStore.dataClass"),
        evidence=_parse_evidence(entry["evidence"], "dataStore.evidence"),
    )


def _parse_dependency(entry: object) -> Dependency:
    entry = _require_object(entry, "dependency")
    _check_keys(entry, _DEPENDENCY_KEYS, "dependency")
    return Dependency(
        dependency_id=entry["dependencyId"],
        source=entry["source"],
        target=entry["target"],
        relation=_enum(DependencyKind, entry["relation"], "dependency.relation"),
        data_class=_enum(DataClass, entry["dataClass"], "dependency.dataClass"),
        evidence=_parse_evidence(entry["evidence"], "dependency.evidence"),
    )


def load_manifest(value: object) -> ArchitectureManifest:
    """Parse and validate a manifest dict, fail-closed on any deviation."""
    if not isinstance(value, dict) or not value:
        raise ManifestError(
            ManifestErrorCode.EMPTY_MANIFEST, "manifest must be a non-empty object"
        )
    keys = set(value)
    if not keys <= _TOP_LEVEL_REQUIRED:
        raise ManifestError(
            ManifestErrorCode.UNKNOWN_FIELD, "manifest has unknown top-level fields"
        )
    if not _TOP_LEVEL_REQUIRED <= keys:
        raise ManifestError(
            ManifestErrorCode.MISSING_FIELD, "manifest is missing top-level fields"
        )
    if value["schemaVersion"] != SCHEMA_VERSION:
        raise ManifestError(
            ManifestErrorCode.UNKNOWN_ENUM, "unsupported manifest schemaVersion"
        )

    boundaries: Tuple[TrustBoundary, ...] = tuple(
        _parse_boundary(entry)
        for entry in _require_list(value["trustBoundaries"], "trustBoundaries")
    )
    components: Tuple[Component, ...] = tuple(
        _parse_component(entry)
        for entry in _require_list(value["components"], "components")
    )
    stores: Tuple[DataStore, ...] = tuple(
        _parse_store(entry) for entry in _require_list(value["dataStores"], "dataStores")
    )
    dependencies: Tuple[Dependency, ...] = tuple(
        _parse_dependency(entry)
        for entry in _require_list(value["dependencies"], "dependencies")
    )
    return ArchitectureManifest(
        manifest_id=value["manifestId"],
        trust_boundaries=boundaries,
        components=components,
        data_stores=stores,
        dependencies=dependencies,
    )
