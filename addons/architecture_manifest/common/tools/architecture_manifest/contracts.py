"""Closed, content-minimized types for an architecture manifest.

The manifest describes the *shape* of a system, not its contents. Real
hostnames, URLs, IP addresses, connection strings, credentials, absolute
paths, and free prose are deliberately absent. Every architectural claim is
reduced to a product-owned opaque token, a finite enum, or a repo-relative
evidence link before it crosses this boundary.

The vocabulary is derived independently from Firestarter/Auggie architecture
needs and neutral public standards:

* W3C PROV (https://www.w3.org/TR/prov-overview/) supplies the entity /
  agent / relation model. Components and data stores are entities; owner roles
  are attributions (``wasAttributedTo``); dependencies are relations. PROV
  derivation (``wasDerivedFrom``) is a partial order, so the ``depends-on`` and
  ``derives-from`` relations must stay acyclic.
* JSON Schema 2020-12 supplies the closed-object contract mirrored under
  ``schemas/``.
* General Mermaid / graph conventions inform the render layer only.

No gallery submission was consulted; only the standards above and this repo's
own sibling add-on idiom.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Optional, Tuple


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
SAFE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_REPO_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,199}$")
IDENTITY_SHAPE = re.compile(r"://|@|\b\d{1,3}(?:\.\d{1,3}){3}\b")
WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")

SCHEMA_VERSION = "1.0"
TOOL_VERSION = "0.1.0"


class ManifestErrorCode(str, Enum):
    """Closed set of deterministic, fail-closed rejection reasons."""

    EMPTY_MANIFEST = "empty-manifest"
    UNKNOWN_FIELD = "unknown-field"
    MISSING_FIELD = "missing-field"
    INVALID_ID = "invalid-id"
    UNKNOWN_ENUM = "unknown-enum"
    INVALID_DIGEST = "invalid-digest"
    ABSOLUTE_PATH = "absolute-path"
    IDENTITY_LEAK = "identity-leak"
    MISSING_EVIDENCE = "missing-evidence"
    DUPLICATE_ID = "duplicate-id"
    UNRESOLVED_REFERENCE = "unresolved-reference"
    CYCLIC_DEPENDENCY = "cyclic-dependency"
    BOUND_EXCEEDED = "bound-exceeded"


class ManifestError(ValueError):
    """Raised for any manifest that violates the closed contract."""

    def __init__(self, code: ManifestErrorCode, message: str) -> None:
        self.code = code
        super().__init__(f"{code.value}: {message}")


def require_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ManifestError(
            ManifestErrorCode.INVALID_ID, f"{field} must be an opaque identifier"
        )
    return value


def require_repo_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError(
            ManifestErrorCode.INVALID_ID, f"{field} must be a repo-relative path"
        )
    if value.startswith("/") or WINDOWS_ABSOLUTE.match(value):
        raise ManifestError(
            ManifestErrorCode.ABSOLUTE_PATH, f"{field} must not be an absolute path"
        )
    if ".." in value.split("/"):
        raise ManifestError(
            ManifestErrorCode.ABSOLUTE_PATH, f"{field} must not traverse parents"
        )
    if IDENTITY_SHAPE.search(value):
        raise ManifestError(
            ManifestErrorCode.IDENTITY_LEAK, f"{field} looks like a URL/host/identity"
        )
    if not SAFE_REPO_PATH.fullmatch(value):
        raise ManifestError(
            ManifestErrorCode.INVALID_ID, f"{field} has disallowed path characters"
        )
    return value


def _enum(cls, value: object, field: str):
    try:
        return cls(value)
    except ValueError as exc:  # noqa: PERF203 - deterministic re-raise
        raise ManifestError(
            ManifestErrorCode.UNKNOWN_ENUM, f"{field} is outside the closed vocabulary"
        ) from exc


class ComponentKind(str, Enum):
    SERVICE = "service"
    LIBRARY = "library"
    JOB = "job"
    GATEWAY = "gateway"
    UI = "ui"
    CLI = "cli"
    ADAPTER = "adapter"
    EXTERNAL_SYSTEM = "external-system"


class DataStoreKind(str, Enum):
    RELATIONAL = "relational"
    DOCUMENT = "document"
    KEY_VALUE = "key-value"
    GRAPH = "graph"
    OBJECT_STORE = "object-store"
    CACHE = "cache"
    SEARCH_INDEX = "search-index"
    QUEUE = "queue"
    SECRET_STORE = "secret-store"


class DependencyKind(str, Enum):
    # Runtime relations may form cycles (A calls B, B calls A).
    CALLS = "calls"
    READS = "reads"
    WRITES = "writes"
    PUBLISHES = "publishes"
    SUBSCRIBES = "subscribes"
    # Ordering relations (PROV derivation partial order) must stay acyclic.
    DEPENDS_ON = "depends-on"
    DERIVES_FROM = "derives-from"


ACYCLIC_RELATIONS = frozenset({DependencyKind.DEPENDS_ON, DependencyKind.DERIVES_FROM})


class OwnerRole(str, Enum):
    PLATFORM = "platform"
    APPLICATION = "application"
    DATA = "data"
    SECURITY = "security"
    INTEGRATION = "integration"
    UNASSIGNED = "unassigned"


class TrustTier(str, Enum):
    PUBLIC = "public"
    PERIMETER = "perimeter"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    ISOLATED = "isolated"


class DataClass(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    REGULATED = "regulated"


class EvidenceKind(str, Enum):
    DOC = "doc"
    TEST = "test"
    SCHEMA = "schema"
    CONFIG = "config"
    DIAGRAM = "diagram"
    RUNBOOK = "runbook"


@dataclass(frozen=True, slots=True)
class EvidenceLink:
    """A repo-relative pointer backing an architectural claim (PROV attribution).

    ``path`` is always relative to the repository root and may carry an optional
    ``sha256:`` digest so a drift check can bind evidence to a known revision.
    Absolute paths, URLs, hosts, and identities are rejected.
    """

    evidence_id: str
    kind: EvidenceKind
    path: str
    digest: Optional[str] = None

    def __post_init__(self) -> None:
        require_id(self.evidence_id, "evidence_id")
        require_repo_path(self.path, "evidence.path")
        if self.digest is not None and not SAFE_DIGEST.fullmatch(self.digest):
            raise ManifestError(
                ManifestErrorCode.INVALID_DIGEST, "evidence.digest must be sha256"
            )

    def to_contract_dict(self) -> dict:
        return {
            "evidenceId": self.evidence_id,
            "kind": self.kind.value,
            "path": self.path,
            "digest": self.digest,
        }

    @property
    def sort_key(self) -> Tuple[str, str, str]:
        return (self.kind.value, self.path, self.evidence_id)


def _parse_evidence(items: object, field: str) -> Tuple[EvidenceLink, ...]:
    if not isinstance(items, list):
        raise ManifestError(ManifestErrorCode.MISSING_FIELD, f"{field} must be a list")
    if len(items) > 32:
        raise ManifestError(ManifestErrorCode.BOUND_EXCEEDED, f"{field} is too large")
    parsed = []
    for entry in items:
        if not isinstance(entry, dict):
            raise ManifestError(
                ManifestErrorCode.MISSING_FIELD, f"{field} entry must be an object"
            )
        keys = set(entry)
        allowed = {"evidenceId", "kind", "path", "digest"}
        required = {"evidenceId", "kind", "path"}
        if not keys <= allowed:
            raise ManifestError(
                ManifestErrorCode.UNKNOWN_FIELD, f"{field} entry has unknown fields"
            )
        if not required <= keys:
            raise ManifestError(
                ManifestErrorCode.MISSING_FIELD, f"{field} entry is missing fields"
            )
        parsed.append(
            EvidenceLink(
                evidence_id=entry["evidenceId"],
                kind=_enum(EvidenceKind, entry["kind"], f"{field}.kind"),
                path=entry["path"],
                digest=entry.get("digest"),
            )
        )
    return tuple(parsed)


@dataclass(frozen=True, slots=True)
class TrustBoundary:
    boundary_id: str
    name: str
    tier: TrustTier

    def __post_init__(self) -> None:
        require_id(self.boundary_id, "boundary_id")
        require_id(self.name, "boundary.name")

    def to_contract_dict(self) -> dict:
        return {
            "boundaryId": self.boundary_id,
            "name": self.name,
            "tier": self.tier.value,
        }


@dataclass(frozen=True, slots=True)
class Component:
    component_id: str
    name: str
    kind: ComponentKind
    boundary_id: str
    owner_role: OwnerRole
    owner_token: str
    evidence: Tuple[EvidenceLink, ...]

    def __post_init__(self) -> None:
        require_id(self.component_id, "component_id")
        require_id(self.name, "component.name")
        require_id(self.boundary_id, "component.boundary_id")
        require_id(self.owner_token, "component.owner_token")
        if not self.evidence:
            raise ManifestError(
                ManifestErrorCode.MISSING_EVIDENCE,
                f"component {self.component_id} needs at least one evidence link",
            )

    def to_contract_dict(self) -> dict:
        return {
            "componentId": self.component_id,
            "name": self.name,
            "kind": self.kind.value,
            "boundaryId": self.boundary_id,
            "ownerRole": self.owner_role.value,
            "ownerToken": self.owner_token,
            "evidence": [
                link.to_contract_dict()
                for link in sorted(self.evidence, key=lambda link: link.sort_key)
            ],
        }


@dataclass(frozen=True, slots=True)
class DataStore:
    store_id: str
    name: str
    kind: DataStoreKind
    boundary_id: str
    owner_role: OwnerRole
    owner_token: str
    data_class: DataClass
    evidence: Tuple[EvidenceLink, ...]

    def __post_init__(self) -> None:
        require_id(self.store_id, "store_id")
        require_id(self.name, "dataStore.name")
        require_id(self.boundary_id, "dataStore.boundary_id")
        require_id(self.owner_token, "dataStore.owner_token")
        if not self.evidence:
            raise ManifestError(
                ManifestErrorCode.MISSING_EVIDENCE,
                f"data store {self.store_id} needs at least one evidence link",
            )

    def to_contract_dict(self) -> dict:
        return {
            "storeId": self.store_id,
            "name": self.name,
            "kind": self.kind.value,
            "boundaryId": self.boundary_id,
            "ownerRole": self.owner_role.value,
            "ownerToken": self.owner_token,
            "dataClass": self.data_class.value,
            "evidence": [
                link.to_contract_dict()
                for link in sorted(self.evidence, key=lambda link: link.sort_key)
            ],
        }


@dataclass(frozen=True, slots=True)
class Dependency:
    dependency_id: str
    source: str
    target: str
    relation: DependencyKind
    data_class: DataClass
    evidence: Tuple[EvidenceLink, ...]

    def __post_init__(self) -> None:
        require_id(self.dependency_id, "dependency_id")
        require_id(self.source, "dependency.source")
        require_id(self.target, "dependency.target")
        if self.source == self.target:
            raise ManifestError(
                ManifestErrorCode.UNRESOLVED_REFERENCE,
                f"dependency {self.dependency_id} is a self-loop",
            )

    def to_contract_dict(self) -> dict:
        return {
            "dependencyId": self.dependency_id,
            "source": self.source,
            "target": self.target,
            "relation": self.relation.value,
            "dataClass": self.data_class.value,
            "evidence": [
                link.to_contract_dict()
                for link in sorted(self.evidence, key=lambda link: link.sort_key)
            ],
        }


@dataclass(frozen=True, slots=True)
class ArchitectureManifest:
    manifest_id: str
    trust_boundaries: Tuple[TrustBoundary, ...]
    components: Tuple[Component, ...]
    data_stores: Tuple[DataStore, ...]
    dependencies: Tuple[Dependency, ...]

    def __post_init__(self) -> None:
        require_id(self.manifest_id, "manifest_id")
        if not self.trust_boundaries or not self.components:
            raise ManifestError(
                ManifestErrorCode.EMPTY_MANIFEST,
                "manifest needs at least one boundary and one component",
            )
        for group, limit in (
            (self.trust_boundaries, 64),
            (self.components, 256),
            (self.data_stores, 256),
            (self.dependencies, 512),
        ):
            if len(group) > limit:
                raise ManifestError(
                    ManifestErrorCode.BOUND_EXCEEDED, "entity count exceeds policy bound"
                )

        boundary_ids = [boundary.boundary_id for boundary in self.trust_boundaries]
        node_ids = [component.component_id for component in self.components] + [
            store.store_id for store in self.data_stores
        ]
        edge_ids = [dependency.dependency_id for dependency in self.dependencies]
        all_ids = boundary_ids + node_ids + edge_ids
        if len(all_ids) != len(set(all_ids)):
            raise ManifestError(
                ManifestErrorCode.DUPLICATE_ID, "entity identifiers must be unique"
            )

        boundary_set = set(boundary_ids)
        for component in self.components:
            if component.boundary_id not in boundary_set:
                raise ManifestError(
                    ManifestErrorCode.UNRESOLVED_REFERENCE,
                    f"component {component.component_id} references an unknown boundary",
                )
        for store in self.data_stores:
            if store.boundary_id not in boundary_set:
                raise ManifestError(
                    ManifestErrorCode.UNRESOLVED_REFERENCE,
                    f"data store {store.store_id} references an unknown boundary",
                )
        node_set = set(node_ids)
        for dependency in self.dependencies:
            if dependency.source not in node_set or dependency.target not in node_set:
                raise ManifestError(
                    ManifestErrorCode.UNRESOLVED_REFERENCE,
                    f"dependency {dependency.dependency_id} references an unknown node",
                )

        self._reject_derivation_cycles()

    def _reject_derivation_cycles(self) -> None:
        adjacency: dict[str, list[str]] = {}
        for dependency in self.dependencies:
            if dependency.relation in ACYCLIC_RELATIONS:
                adjacency.setdefault(dependency.source, []).append(dependency.target)
        # Deterministic DFS three-color cycle detection.
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {}

        def visit(node: str) -> None:
            color[node] = GRAY
            for nxt in sorted(adjacency.get(node, ())):
                state = color.get(nxt, WHITE)
                if state == GRAY:
                    raise ManifestError(
                        ManifestErrorCode.CYCLIC_DEPENDENCY,
                        "depends-on / derives-from edges must be acyclic",
                    )
                if state == WHITE:
                    visit(nxt)
            color[node] = BLACK

        for node in sorted(adjacency):
            if color.get(node, WHITE) == WHITE:
                visit(node)

    def to_contract_dict(self) -> dict:
        """Canonical, order-stable projection of the manifest."""
        return {
            "schemaVersion": SCHEMA_VERSION,
            "manifestId": self.manifest_id,
            "trustBoundaries": [
                boundary.to_contract_dict()
                for boundary in sorted(
                    self.trust_boundaries, key=lambda item: item.boundary_id
                )
            ],
            "components": [
                component.to_contract_dict()
                for component in sorted(
                    self.components, key=lambda item: item.component_id
                )
            ],
            "dataStores": [
                store.to_contract_dict()
                for store in sorted(self.data_stores, key=lambda item: item.store_id)
            ],
            "dependencies": [
                dependency.to_contract_dict()
                for dependency in sorted(
                    self.dependencies, key=lambda item: item.dependency_id
                )
            ],
        }

    @property
    def canonical_digest(self) -> str:
        return canonical_digest(self.to_contract_dict())


def canonical_digest(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
