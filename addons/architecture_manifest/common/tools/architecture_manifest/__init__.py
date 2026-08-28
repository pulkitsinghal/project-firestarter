"""Source-only, deterministic architecture manifest contract and renderers."""

from .contracts import (
    ArchitectureManifest,
    Component,
    ComponentKind,
    DataClass,
    DataStore,
    DataStoreKind,
    Dependency,
    DependencyKind,
    EvidenceKind,
    EvidenceLink,
    ManifestError,
    ManifestErrorCode,
    OwnerRole,
    TrustBoundary,
    TrustTier,
)
from .drift import DriftReport, DriftStatus, check_drift
from .manifest import load_manifest
from .render import (
    RenderEnvelope,
    render,
    render_anatomy,
    render_envelope,
    render_mermaid,
)

__all__ = [
    "ArchitectureManifest",
    "Component",
    "ComponentKind",
    "DataClass",
    "DataStore",
    "DataStoreKind",
    "Dependency",
    "DependencyKind",
    "DriftReport",
    "DriftStatus",
    "EvidenceKind",
    "EvidenceLink",
    "ManifestError",
    "ManifestErrorCode",
    "OwnerRole",
    "RenderEnvelope",
    "TrustBoundary",
    "TrustTier",
    "check_drift",
    "load_manifest",
    "render",
    "render_anatomy",
    "render_envelope",
    "render_mermaid",
]

__version__ = "0.1.0"
