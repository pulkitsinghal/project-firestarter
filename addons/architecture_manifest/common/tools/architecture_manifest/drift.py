"""Deterministic drift check between a manifest and a rendered artifact.

Given a manifest and the current text of a rendered artifact (Mermaid or the
ANATOMY-style table), :func:`check_drift` reports whether the artifact is
``current`` (matches what the manifest would render today) or ``stale``.

Comparison is by *normalized content*, defined in :mod:`render`: line endings
are unified, trailing whitespace per line is stripped, and trailing blank lines
are dropped, before a SHA-256 digest is taken. This tolerates cosmetic
whitespace/EOL churn while surfacing any semantic change.

The check is fail-closed: a malformed manifest, an unknown artifact kind, or a
non-string artifact yields a ``malformed`` report (never a false ``current``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .contracts import (
    ArchitectureManifest,
    ManifestError,
    SCHEMA_VERSION,
    TOOL_VERSION,
)
from .manifest import load_manifest
from .render import ARTIFACT_KINDS, content_digest, render


class DriftStatus(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    MALFORMED = "malformed"


@dataclass(frozen=True, slots=True)
class DriftReport:
    artifact_kind: str
    status: DriftStatus
    manifest_id: Optional[str]
    expected_digest: Optional[str]
    actual_digest: Optional[str]

    @property
    def is_current(self) -> bool:
        return self.status is DriftStatus.CURRENT

    def to_contract_dict(self) -> dict:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "toolVersion": TOOL_VERSION,
            "artifactKind": self.artifact_kind,
            "status": self.status.value,
            "manifestId": self.manifest_id,
            "expectedDigest": self.expected_digest,
            "actualDigest": self.actual_digest,
        }


def _coerce_manifest(manifest: object) -> ArchitectureManifest:
    if isinstance(manifest, ArchitectureManifest):
        return manifest
    return load_manifest(manifest)


def check_drift(
    manifest: object, rendered_text: object, artifact_kind: str
) -> DriftReport:
    """Report whether ``rendered_text`` is current vs. what ``manifest`` renders.

    ``manifest`` may be an :class:`ArchitectureManifest` or a raw dict (which is
    loaded/validated first). Any validation failure is reported as ``malformed``.
    """
    if artifact_kind not in ARTIFACT_KINDS:
        return DriftReport(
            artifact_kind=str(artifact_kind),
            status=DriftStatus.MALFORMED,
            manifest_id=None,
            expected_digest=None,
            actual_digest=None,
        )
    try:
        parsed = _coerce_manifest(manifest)
    except (ManifestError, ValueError, TypeError):
        return DriftReport(
            artifact_kind=artifact_kind,
            status=DriftStatus.MALFORMED,
            manifest_id=None,
            expected_digest=None,
            actual_digest=None,
        )
    if not isinstance(rendered_text, str):
        return DriftReport(
            artifact_kind=artifact_kind,
            status=DriftStatus.MALFORMED,
            manifest_id=parsed.manifest_id,
            expected_digest=content_digest(render(parsed, artifact_kind)),
            actual_digest=None,
        )

    expected = content_digest(render(parsed, artifact_kind))
    actual = content_digest(rendered_text)
    status = DriftStatus.CURRENT if expected == actual else DriftStatus.STALE
    return DriftReport(
        artifact_kind=artifact_kind,
        status=status,
        manifest_id=parsed.manifest_id,
        expected_digest=expected,
        actual_digest=actual,
    )
