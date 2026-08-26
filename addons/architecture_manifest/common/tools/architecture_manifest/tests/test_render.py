from __future__ import annotations

import unittest

from ..drift import DriftStatus, check_drift
from ..manifest import load_manifest
from ..render import (
    ARTIFACT_ANATOMY,
    ARTIFACT_MERMAID,
    normalize,
    render,
    render_anatomy,
    render_envelope,
    render_mermaid,
)
from .common import load_golden, valid_manifest_dict


class RenderDeterminismTests(unittest.TestCase):
    def test_mermaid_is_deterministic_and_order_independent(self) -> None:
        data = valid_manifest_dict()
        shuffled = valid_manifest_dict()
        shuffled["components"].reverse()
        shuffled["dependencies"].reverse()
        shuffled["trustBoundaries"].reverse()
        first = render_mermaid(load_manifest(data))
        second = render_mermaid(load_manifest(shuffled))
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("flowchart TD\n"))

    def test_anatomy_is_deterministic_and_order_independent(self) -> None:
        data = valid_manifest_dict()
        shuffled = valid_manifest_dict()
        shuffled["dataStores"].reverse()
        shuffled["components"].reverse()
        first = render_anatomy(load_manifest(data))
        second = render_anatomy(load_manifest(shuffled))
        self.assertEqual(first, second)
        self.assertIn("## Components", first)
        self.assertIn("## Trust boundaries", first)
        self.assertIn("## Dependencies", first)

    def test_mermaid_uses_positional_keys_not_raw_ids(self) -> None:
        manifest = load_manifest(load_golden())
        text = render_mermaid(manifest)
        # Every dependency line references positional node keys.
        self.assertIn(" -->|", text)
        self.assertIn("[(", text)  # a data-store cylinder is present
        self.assertIn("{" * 2, text)  # a gateway/external hexagon is present

    def test_render_dispatch_rejects_unknown_kind(self) -> None:
        manifest = load_manifest(valid_manifest_dict())
        with self.assertRaises(ValueError):
            render(manifest, "graphviz")

    def test_envelope_counts_and_digest(self) -> None:
        manifest = load_manifest(load_golden())
        envelope = render_envelope(manifest, ARTIFACT_MERMAID)
        payload = envelope.to_contract_dict()
        self.assertEqual(payload["componentCount"], 6)
        self.assertEqual(payload["dataStoreCount"], 3)
        self.assertEqual(payload["dependencyCount"], 11)
        self.assertEqual(payload["boundaryCount"], 3)
        self.assertTrue(payload["contentDigest"].startswith("sha256:"))


class DriftDetectionTests(unittest.TestCase):
    def test_freshly_rendered_artifact_is_current(self) -> None:
        manifest = load_manifest(load_golden())
        for kind in (ARTIFACT_MERMAID, ARTIFACT_ANATOMY):
            report = check_drift(manifest, render(manifest, kind), kind)
            self.assertIs(report.status, DriftStatus.CURRENT, kind)
            self.assertEqual(report.expected_digest, report.actual_digest)

    def test_cosmetic_whitespace_does_not_trip_drift(self) -> None:
        manifest = load_manifest(load_golden())
        text = render_mermaid(manifest)
        noisy = "\r\n".join(line + "   " for line in text.split("\n")) + "\n\n\n"
        report = check_drift(manifest, noisy, ARTIFACT_MERMAID)
        self.assertIs(report.status, DriftStatus.CURRENT)

    def test_semantic_change_makes_artifact_stale(self) -> None:
        manifest = load_manifest(load_golden())
        stale = render_mermaid(manifest).replace("calls", "reads", 1)
        report = check_drift(manifest, stale, ARTIFACT_MERMAID)
        self.assertIs(report.status, DriftStatus.STALE)
        self.assertNotEqual(report.expected_digest, report.actual_digest)

    def test_drift_accepts_raw_dict_manifest(self) -> None:
        data = load_golden()
        report = check_drift(data, render(load_manifest(data), ARTIFACT_ANATOMY), ARTIFACT_ANATOMY)
        self.assertIs(report.status, DriftStatus.CURRENT)

    def test_drift_report_contract_shape(self) -> None:
        manifest = load_manifest(valid_manifest_dict())
        report = check_drift(manifest, render(manifest, ARTIFACT_MERMAID), ARTIFACT_MERMAID)
        payload = report.to_contract_dict()
        self.assertEqual(
            set(payload),
            {
                "schemaVersion",
                "toolVersion",
                "artifactKind",
                "status",
                "manifestId",
                "expectedDigest",
                "actualDigest",
            },
        )

    def test_normalize_drops_trailing_blank_lines(self) -> None:
        self.assertEqual(normalize("a\nb\n\n\n"), "a\nb")
        self.assertEqual(normalize("a  \r\nb\t\n"), "a\nb")


if __name__ == "__main__":
    unittest.main()
