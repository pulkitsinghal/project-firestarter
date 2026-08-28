from __future__ import annotations

import copy
import json
from pathlib import Path


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN_FIXTURE = FIXTURES / "architecture-manifest.synthetic.json"
ADVERSARIAL_FIXTURE = FIXTURES / "adversarial-manifests.synthetic.json"


def load_golden() -> dict:
    return json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))


def load_adversarial() -> dict:
    return json.loads(ADVERSARIAL_FIXTURE.read_text(encoding="utf-8"))


def valid_manifest_dict() -> dict:
    """A compact, schema-valid manifest returned fresh on every call."""
    return copy.deepcopy(_VALID)


_VALID = {
    "schemaVersion": "1.0",
    "manifestId": "unit-fixture",
    "trustBoundaries": [
        {"boundaryId": "app", "name": "application-tier", "tier": "internal"},
        {"boundaryId": "data", "name": "data-tier", "tier": "restricted"},
    ],
    "components": [
        {
            "componentId": "c-a",
            "name": "svc-a",
            "kind": "service",
            "boundaryId": "app",
            "ownerRole": "application",
            "ownerToken": "team-app",
            "evidence": [
                {"evidenceId": "ev-a", "kind": "doc", "path": "docs/a.md", "digest": None}
            ],
        },
        {
            "componentId": "c-b",
            "name": "svc-b",
            "kind": "library",
            "boundaryId": "app",
            "ownerRole": "platform",
            "ownerToken": "team-platform",
            "evidence": [
                {"evidenceId": "ev-b", "kind": "doc", "path": "docs/b.md"}
            ],
        },
    ],
    "dataStores": [
        {
            "storeId": "s-a",
            "name": "store-a",
            "kind": "relational",
            "boundaryId": "data",
            "ownerRole": "data",
            "ownerToken": "team-data",
            "dataClass": "confidential",
            "evidence": [
                {"evidenceId": "ev-s", "kind": "doc", "path": "docs/s.md"}
            ],
        }
    ],
    "dependencies": [
        {
            "dependencyId": "d-1",
            "source": "c-a",
            "target": "c-b",
            "relation": "depends-on",
            "dataClass": "public",
            "evidence": [],
        },
        {
            "dependencyId": "d-2",
            "source": "c-a",
            "target": "s-a",
            "relation": "reads",
            "dataClass": "confidential",
            "evidence": [],
        },
    ],
}
