from __future__ import annotations

import unittest

from ..contracts import ManifestError, ManifestErrorCode
from ..drift import DriftStatus, check_drift
from ..manifest import load_manifest
from ..render import ARTIFACT_MERMAID, render
from .common import load_adversarial, valid_manifest_dict


def _mutate(fn):
    data = valid_manifest_dict()
    fn(data)
    return data


def build_case(case_id: str) -> dict:
    """Return a malformed manifest dict for the given adversarial scenario id."""
    if case_id == "A01":
        return _mutate(lambda d: d.__setitem__("surprise", True))
    if case_id == "A02":
        return _mutate(lambda d: d.pop("dependencies"))
    if case_id == "A03":
        return {}
    if case_id == "A04":
        return _mutate(lambda d: d["components"][0].__setitem__("kind", "wormhole"))
    if case_id == "A05":
        return _mutate(lambda d: d["components"][0].__setitem__("componentId", "bad id!"))
    if case_id == "A06":
        return _mutate(
            lambda d: d["components"][0]["evidence"][0].__setitem__("digest", "sha256:zz")
        )
    if case_id == "A07":
        return _mutate(lambda d: d["components"][1].__setitem__("componentId", "c-a"))
    if case_id == "A08":
        return _mutate(lambda d: d["components"][0].__setitem__("boundaryId", "ghost"))
    if case_id == "A09":
        return _mutate(lambda d: d["dependencies"][0].__setitem__("target", "ghost"))
    if case_id == "A10":
        return _mutate(
            lambda d: d["dependencies"].append(
                {
                    "dependencyId": "d-cycle",
                    "source": "c-b",
                    "target": "c-a",
                    "relation": "depends-on",
                    "dataClass": "public",
                    "evidence": [],
                }
            )
        )
    if case_id == "A11":
        return _mutate(lambda d: d["dependencies"][0].__setitem__("target", "c-a"))
    if case_id == "A12":
        return _mutate(
            lambda d: d["components"][0]["evidence"][0].__setitem__("path", "/etc/passwd")
        )
    if case_id == "A13":
        return _mutate(lambda d: d["components"][0].__setitem__("evidence", []))
    if case_id == "A14":
        return _mutate(
            lambda d: d["components"][0]["evidence"][0].__setitem__(
                "path", "docs/note@internal-host.md"
            )
        )
    if case_id == "A15":
        return {}
    raise AssertionError(f"unknown adversarial case: {case_id}")


def execute_fixture_scenario(case_id: str) -> ManifestErrorCode:
    """Load the malformed manifest and return its closed rejection code."""
    try:
        load_manifest(build_case(case_id))
    except ManifestError as error:
        return error.code
    raise AssertionError(f"{case_id} was accepted but should have failed closed")


class AdversarialManifestTests(unittest.TestCase):
    def _assert(self, case_id: str, expected: ManifestErrorCode) -> None:
        self.assertIs(execute_fixture_scenario(case_id), expected)

    def test_structural_rejections(self) -> None:
        self._assert("A01", ManifestErrorCode.UNKNOWN_FIELD)
        self._assert("A02", ManifestErrorCode.MISSING_FIELD)
        self._assert("A03", ManifestErrorCode.EMPTY_MANIFEST)
        self._assert("A04", ManifestErrorCode.UNKNOWN_ENUM)
        self._assert("A05", ManifestErrorCode.INVALID_ID)
        self._assert("A06", ManifestErrorCode.INVALID_DIGEST)

    def test_reference_rejections(self) -> None:
        self._assert("A07", ManifestErrorCode.DUPLICATE_ID)
        self._assert("A08", ManifestErrorCode.UNRESOLVED_REFERENCE)
        self._assert("A09", ManifestErrorCode.UNRESOLVED_REFERENCE)

    def test_cycle_rejections(self) -> None:
        self._assert("A10", ManifestErrorCode.CYCLIC_DEPENDENCY)
        self._assert("A11", ManifestErrorCode.UNRESOLVED_REFERENCE)

    def test_privacy_absolute_path(self) -> None:
        self._assert("A12", ManifestErrorCode.ABSOLUTE_PATH)

    def test_evidence_required(self) -> None:
        self._assert("A13", ManifestErrorCode.MISSING_EVIDENCE)

    def test_identity_leak(self) -> None:
        self._assert("A14", ManifestErrorCode.IDENTITY_LEAK)

    def test_render_and_drift_fail_closed(self) -> None:
        # A malformed manifest never reaches the render layer.
        self._assert("A15", ManifestErrorCode.EMPTY_MANIFEST)
        report = check_drift({}, "flowchart TD\n", ARTIFACT_MERMAID)
        self.assertIs(report.status, DriftStatus.MALFORMED)
        self.assertIsNone(report.expected_digest)
        # Unknown artifact kind is also fail-closed.
        valid = load_manifest(valid_manifest_dict())
        unknown = check_drift(valid, render(valid, ARTIFACT_MERMAID), "svg")
        self.assertIs(unknown.status, DriftStatus.MALFORMED)
        # Non-string artifact text is fail-closed but reports the expected digest.
        non_string = check_drift(valid, None, ARTIFACT_MERMAID)
        self.assertIs(non_string.status, DriftStatus.MALFORMED)
        self.assertIsNone(non_string.actual_digest)
        self.assertIsNotNone(non_string.expected_digest)

    def test_every_declared_scenario_fails_closed(self) -> None:
        fixture = load_adversarial()
        for scenario in fixture["scenarios"]:
            with self.subTest(scenario=scenario["id"]):
                observed = execute_fixture_scenario(scenario["id"])
                self.assertEqual(observed.value, scenario["expectedCode"])


if __name__ == "__main__":
    unittest.main()
