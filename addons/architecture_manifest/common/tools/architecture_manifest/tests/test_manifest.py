from __future__ import annotations

import copy
import unittest

from ..contracts import (
    ArchitectureManifest,
    ManifestError,
    ManifestErrorCode,
)
from ..manifest import load_manifest
from .common import load_golden, valid_manifest_dict


class ManifestContractTests(unittest.TestCase):
    def test_golden_fixture_loads_and_is_closed(self) -> None:
        manifest = load_manifest(load_golden())
        self.assertIsInstance(manifest, ArchitectureManifest)
        self.assertEqual(manifest.manifest_id, "sample-platform")
        self.assertEqual(len(manifest.components), 6)
        self.assertEqual(len(manifest.data_stores), 3)
        self.assertEqual(len(manifest.dependencies), 11)

    def test_loader_does_not_mutate_input(self) -> None:
        data = load_golden()
        snapshot = copy.deepcopy(data)
        load_manifest(data)
        self.assertEqual(data, snapshot)

    def test_reducer_is_order_independent_and_deterministic(self) -> None:
        data = valid_manifest_dict()
        shuffled = valid_manifest_dict()
        shuffled["components"].reverse()
        shuffled["trustBoundaries"].reverse()
        shuffled["dependencies"].reverse()

        first = load_manifest(data)
        second = load_manifest(shuffled)
        self.assertEqual(first.to_contract_dict(), second.to_contract_dict())
        self.assertEqual(first.canonical_digest, second.canonical_digest)

    def test_canonical_dict_sorts_every_collection(self) -> None:
        manifest = load_manifest(valid_manifest_dict())
        canonical = manifest.to_contract_dict()
        self.assertEqual(
            [c["componentId"] for c in canonical["components"]],
            sorted(c["componentId"] for c in canonical["components"]),
        )
        self.assertEqual(
            [d["dependencyId"] for d in canonical["dependencies"]],
            sorted(d["dependencyId"] for d in canonical["dependencies"]),
        )

    def test_round_trip_through_contract_dict_is_stable(self) -> None:
        manifest = load_manifest(valid_manifest_dict())
        reloaded = load_manifest(manifest.to_contract_dict())
        self.assertEqual(manifest.canonical_digest, reloaded.canonical_digest)

    def test_runtime_relations_may_cycle(self) -> None:
        data = valid_manifest_dict()
        data["dependencies"] = [
            {
                "dependencyId": "d-1",
                "source": "c-a",
                "target": "c-b",
                "relation": "calls",
                "dataClass": "public",
                "evidence": [],
            },
            {
                "dependencyId": "d-2",
                "source": "c-b",
                "target": "c-a",
                "relation": "calls",
                "dataClass": "public",
                "evidence": [],
            },
        ]
        manifest = load_manifest(data)
        self.assertEqual(len(manifest.dependencies), 2)

    def test_error_carries_closed_code(self) -> None:
        data = valid_manifest_dict()
        data["surprise"] = True
        with self.assertRaises(ManifestError) as ctx:
            load_manifest(data)
        self.assertIs(ctx.exception.code, ManifestErrorCode.UNKNOWN_FIELD)


if __name__ == "__main__":
    unittest.main()
