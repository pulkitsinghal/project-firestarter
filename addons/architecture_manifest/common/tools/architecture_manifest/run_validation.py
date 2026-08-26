"""Hermetic package validation entrypoint.

Verifies (a) every JSON schema parses, is draft 2020-12, rejects unknown fields,
and stays in lockstep with the Python enums; (b) the synthetic fixtures are
versioned, synthetic-only, and map every adversarial scenario to a real,
callable package test method; (c) the golden manifest loads, renders, and is
drift-current; (d) the static privacy scan is clean; then loads and runs the
unittest suites and prints ``architecture_manifest: PASS``.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import re
import unittest

from .contracts import (
    ComponentKind,
    DataClass,
    DataStoreKind,
    DependencyKind,
    EvidenceKind,
    ManifestErrorCode,
    OwnerRole,
    TrustTier,
)
from .drift import DriftStatus, check_drift
from .manifest import load_manifest
from .privacy_scan import scan
from .render import ARTIFACT_ANATOMY, ARTIFACT_KINDS, ARTIFACT_MERMAID, render


ROOT = Path(__file__).resolve().parent

REQUIRED_CATEGORIES = {
    "structural",
    "reference",
    "cycle",
    "privacy",
    "evidence",
    "identity",
}


def _enum_values(enum_cls) -> set:
    return {member.value for member in enum_cls}


def verify_contract_artifacts() -> None:
    schemas = sorted((ROOT / "schemas").glob("*.schema.json"))
    if len(schemas) < 3:
        raise AssertionError("expected the complete versioned schema set")
    parsed = {}
    for path in schemas:
        schema = json.loads(path.read_text(encoding="utf-8"))
        parsed[path.name] = schema
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise AssertionError(f"{path.name} has the wrong JSON Schema draft")
        if schema.get("additionalProperties") is not False:
            raise AssertionError(f"{path.name} root must reject unknown fields")

    manifest_schema = parsed["architecture-manifest-1.0.schema.json"]
    defs = manifest_schema["$defs"]
    lockstep = (
        (defs["component"]["properties"]["kind"]["enum"], ComponentKind, "component kind"),
        (defs["dataStore"]["properties"]["kind"]["enum"], DataStoreKind, "data store kind"),
        (defs["dependency"]["properties"]["relation"]["enum"], DependencyKind, "relation"),
        (defs["component"]["properties"]["ownerRole"]["enum"], OwnerRole, "owner role"),
        (defs["dataStore"]["properties"]["ownerRole"]["enum"], OwnerRole, "owner role"),
        (defs["trustBoundary"]["properties"]["tier"]["enum"], TrustTier, "trust tier"),
        (defs["dataClass"]["enum"], DataClass, "data class"),
        (defs["evidenceLink"]["properties"]["kind"]["enum"], EvidenceKind, "evidence kind"),
    )
    for enum_values, enum_cls, label in lockstep:
        if set(enum_values) != _enum_values(enum_cls):
            raise AssertionError(f"manifest schema and {label} enum drifted")

    drift_schema = parsed["render-drift-report-1.0.schema.json"]
    if set(drift_schema["properties"]["status"]["enum"]) != _enum_values(DriftStatus):
        raise AssertionError("drift schema and DriftStatus enum drifted")
    if set(drift_schema["properties"]["artifactKind"]["enum"]) != ARTIFACT_KINDS:
        raise AssertionError("drift schema artifact kinds drifted")

    envelope_schema = parsed["manifest-render-envelope-1.0.schema.json"]
    if set(envelope_schema["properties"]["artifactKind"]["enum"]) != ARTIFACT_KINDS:
        raise AssertionError("envelope schema artifact kinds drifted")

    _verify_fixtures()

    findings = scan()
    if findings:
        raise AssertionError("; ".join(findings))


def _verify_fixtures() -> None:
    # Golden manifest: loads, renders, and is drift-current for every artifact.
    golden = json.loads(
        (ROOT / "fixtures" / "architecture-manifest.synthetic.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = load_manifest(golden)
    for kind in (ARTIFACT_MERMAID, ARTIFACT_ANATOMY):
        report = check_drift(manifest, render(manifest, kind), kind)
        if report.status is not DriftStatus.CURRENT:
            raise AssertionError(f"golden fixture is not drift-current for {kind}")

    # Adversarial corpus: versioned, synthetic-only, fully covered.
    fixture = json.loads(
        (ROOT / "fixtures" / "adversarial-manifests.synthetic.json").read_text(
            encoding="utf-8"
        )
    )
    if set(fixture) != {
        "schemaVersion",
        "syntheticOnly",
        "authorityBoundary",
        "coverage",
        "scenarios",
    }:
        raise AssertionError("adversarial fixture has unknown root fields")
    if fixture["schemaVersion"] != "1.0" or fixture["syntheticOnly"] is not True:
        raise AssertionError("adversarial fixture must be versioned and synthetic-only")

    scenarios = fixture["scenarios"]
    ids = [scenario["id"] for scenario in scenarios]
    if len(ids) != len(set(ids)):
        raise AssertionError("scenario IDs must be unique")
    coverage = fixture["coverage"]
    if set(coverage) != set(ids):
        raise AssertionError("each synthetic scenario must map to an executable test")

    coverage_pattern = re.compile(
        r"^test_(?:manifest|render|adversarial)\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$"
    )
    if not all(
        isinstance(name, str) and coverage_pattern.fullmatch(name)
        for name in coverage.values()
    ):
        raise AssertionError("fixture coverage must name package test methods")
    for name in set(coverage.values()):
        module_name, class_name, method_name = name.split(".")
        module = importlib.import_module(f"{__package__}.tests.{module_name}")
        test_method = getattr(getattr(module, class_name, None), method_name, None)
        if not callable(test_method):
            raise AssertionError(f"fixture coverage test is not executable: {name}")

    if {scenario["category"] for scenario in scenarios} != REQUIRED_CATEGORIES:
        raise AssertionError("adversarial corpus is missing a category")
    reason_codes = _enum_values(ManifestErrorCode)
    for scenario in scenarios:
        if set(scenario) != {"id", "category", "transition", "expectedCode"}:
            raise AssertionError(f"{scenario['id']} has unknown fields")
        if scenario["expectedCode"] not in reason_codes:
            raise AssertionError(f"{scenario['id']} has an unknown reason code")


def main() -> int:
    verify_contract_artifacts()
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        [
            "tools.architecture_manifest.tests.test_manifest",
            "tools.architecture_manifest.tests.test_render",
            "tools.architecture_manifest.tests.test_adversarial",
        ]
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1
    print("architecture_manifest: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
