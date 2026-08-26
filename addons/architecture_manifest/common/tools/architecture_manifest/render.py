"""Deterministic render layer: Mermaid graph + ANATOMY-style Markdown table.

Both renderers are pure functions of the manifest. They contain no timestamps,
no randomness, no environment lookups, and no absolute paths. Ordering is fully
determined by sorted opaque identifiers, so the same manifest always yields
byte-identical output regardless of input ordering. Node keys are assigned
positionally (``n0``, ``n1`` ...) from the sorted node list so that arbitrary
opaque IDs (which may contain ``.`` or ``:``) never break Mermaid syntax.

Mermaid syntax follows general public conventions (flowchart with subgraphs,
cylinder nodes for stores, hexagon nodes for gateways/external systems).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .contracts import (
    ArchitectureManifest,
    ComponentKind,
    SCHEMA_VERSION,
    TOOL_VERSION,
)


ARTIFACT_MERMAID = "mermaid"
ARTIFACT_ANATOMY = "anatomy"
ARTIFACT_KINDS = frozenset({ARTIFACT_MERMAID, ARTIFACT_ANATOMY})

_HEX_KINDS = frozenset({ComponentKind.GATEWAY, ComponentKind.EXTERNAL_SYSTEM})


def _node_keys(manifest: ArchitectureManifest) -> Dict[str, str]:
    """Assign stable positional Mermaid keys to every node id (sorted)."""
    node_ids = sorted(
        [component.component_id for component in manifest.components]
        + [store.store_id for store in manifest.data_stores]
    )
    return {node_id: f"n{index}" for index, node_id in enumerate(node_ids)}


def _mermaid_node(key: str, label: str, shape: str) -> str:
    if shape == "cylinder":
        return f'{key}[("{label}")]'
    if shape == "hexagon":
        # Mermaid hexagon delimiters are a doubled brace pair; build them at
        # runtime so this source carries no literal token-shaped double brace.
        hex_open, hex_close = "{" * 2, "}" * 2
        return f'{key}{hex_open}"{label}"{hex_close}'
    return f'{key}["{label}"]'


def render_mermaid(manifest: ArchitectureManifest) -> str:
    """Render a deterministic Mermaid ``flowchart TD`` for the manifest."""
    keys = _node_keys(manifest)
    components = {c.component_id: c for c in manifest.components}
    stores = {s.store_id: s for s in manifest.data_stores}

    lines = ["flowchart TD"]
    for boundary in sorted(manifest.trust_boundaries, key=lambda b: b.boundary_id):
        lines.append(f'  subgraph {boundary.boundary_id}["{boundary.name} :: {boundary.tier.value}"]')
        members = sorted(
            [c.component_id for c in manifest.components if c.boundary_id == boundary.boundary_id]
            + [s.store_id for s in manifest.data_stores if s.boundary_id == boundary.boundary_id]
        )
        for node_id in members:
            if node_id in components:
                comp = components[node_id]
                shape = "hexagon" if comp.kind in _HEX_KINDS else "box"
                label = f"{comp.name}<br/>{comp.kind.value}"
            else:
                store = stores[node_id]
                shape = "cylinder"
                label = f"{store.name}<br/>{store.kind.value}"
            lines.append(f"    {_mermaid_node(keys[node_id], label, shape)}")
        lines.append("  end")

    for dependency in sorted(manifest.dependencies, key=lambda d: d.dependency_id):
        src = keys[dependency.source]
        dst = keys[dependency.target]
        lines.append(f"  {src} -->|{dependency.relation.value}| {dst}")

    return "\n".join(lines) + "\n"


def _md_cell(value: str) -> str:
    return value.replace("|", r"\|")


def render_anatomy(manifest: ArchitectureManifest) -> str:
    """Render a deterministic ANATOMY-style Markdown table set for the manifest."""
    lines = [f"# Architecture manifest: {manifest.manifest_id}", ""]

    lines.append("## Trust boundaries")
    lines.append("")
    lines.append("| Boundary | Name | Tier |")
    lines.append("| --- | --- | --- |")
    for boundary in sorted(manifest.trust_boundaries, key=lambda b: b.boundary_id):
        lines.append(
            f"| {_md_cell(boundary.boundary_id)} | {_md_cell(boundary.name)} "
            f"| {boundary.tier.value} |"
        )
    lines.append("")

    lines.append("## Components")
    lines.append("")
    lines.append("| ID | Name | Kind | Boundary | Owner role | Owner | Evidence |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for component in sorted(manifest.components, key=lambda c: c.component_id):
        lines.append(
            f"| {_md_cell(component.component_id)} | {_md_cell(component.name)} "
            f"| {component.kind.value} | {_md_cell(component.boundary_id)} "
            f"| {component.owner_role.value} | {_md_cell(component.owner_token)} "
            f"| {_md_cell(_evidence_cell(component.evidence))} |"
        )
    lines.append("")

    lines.append("## Data stores")
    lines.append("")
    lines.append(
        "| ID | Name | Kind | Boundary | Owner role | Owner | Data class | Evidence |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for store in sorted(manifest.data_stores, key=lambda s: s.store_id):
        lines.append(
            f"| {_md_cell(store.store_id)} | {_md_cell(store.name)} "
            f"| {store.kind.value} | {_md_cell(store.boundary_id)} "
            f"| {store.owner_role.value} | {_md_cell(store.owner_token)} "
            f"| {store.data_class.value} | {_md_cell(_evidence_cell(store.evidence))} |"
        )
    lines.append("")

    lines.append("## Dependencies")
    lines.append("")
    lines.append("| ID | Source | Target | Relation | Data class | Evidence |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for dependency in sorted(manifest.dependencies, key=lambda d: d.dependency_id):
        lines.append(
            f"| {_md_cell(dependency.dependency_id)} | {_md_cell(dependency.source)} "
            f"| {_md_cell(dependency.target)} | {dependency.relation.value} "
            f"| {dependency.data_class.value} "
            f"| {_md_cell(_evidence_cell(dependency.evidence))} |"
        )
    lines.append("")

    return "\n".join(lines)


def _evidence_cell(evidence) -> str:
    if not evidence:
        return "-"
    return "; ".join(
        f"{link.kind.value}:{link.path}"
        for link in sorted(evidence, key=lambda link: link.sort_key)
    )


def render(manifest: ArchitectureManifest, artifact_kind: str) -> str:
    """Render one artifact by kind. Raises ValueError for an unknown kind."""
    if artifact_kind == ARTIFACT_MERMAID:
        return render_mermaid(manifest)
    if artifact_kind == ARTIFACT_ANATOMY:
        return render_anatomy(manifest)
    raise ValueError(f"unknown artifact kind: {artifact_kind}")


def normalize(text: str) -> str:
    """Normalized-content form used for stable comparison and digests.

    Line endings are unified to ``\\n``, trailing whitespace on each line is
    stripped, and trailing blank lines are dropped. Leading/interior structure
    is preserved so semantic changes always surface.
    """
    if not isinstance(text, str):
        raise TypeError("render text must be a string")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    stripped = [line.rstrip() for line in lines]
    while stripped and stripped[-1] == "":
        stripped.pop()
    return "\n".join(stripped)


def content_digest(text: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RenderEnvelope:
    artifact_kind: str
    manifest_id: str
    component_count: int
    data_store_count: int
    dependency_count: int
    boundary_count: int
    content_digest: str

    def to_contract_dict(self) -> dict:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "toolVersion": TOOL_VERSION,
            "artifactKind": self.artifact_kind,
            "manifestId": self.manifest_id,
            "componentCount": self.component_count,
            "dataStoreCount": self.data_store_count,
            "dependencyCount": self.dependency_count,
            "boundaryCount": self.boundary_count,
            "contentDigest": self.content_digest,
        }


def render_envelope(manifest: ArchitectureManifest, artifact_kind: str) -> RenderEnvelope:
    if artifact_kind not in ARTIFACT_KINDS:
        raise ValueError(f"unknown artifact kind: {artifact_kind}")
    text = render(manifest, artifact_kind)
    return RenderEnvelope(
        artifact_kind=artifact_kind,
        manifest_id=manifest.manifest_id,
        component_count=len(manifest.components),
        data_store_count=len(manifest.data_stores),
        dependency_count=len(manifest.dependencies),
        boundary_count=len(manifest.trust_boundaries),
        content_digest=content_digest(text),
    )
