"""Hermetic package validation entrypoint.

Verifies the JSON schemas stay locked in step with the closed contract enums,
that the synthetic fixtures are well formed and map to executable tests, that
the source tree is free of network/process capability, and finally runs the
deterministic test suites. Prints ``mcp_security_gate: PASS`` on success.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import re
import unittest

from .contracts import (
    AnnotationHandling,
    CheckId,
    DegradedBehavior,
    Disposition,
    Posture,
    ReasonCode,
    Reversibility,
    RiskManifest,
    ToolEffect,
    TokenPosture,
    Verdict,
)
from .gate import evaluate
from .privacy_scan import scan


ROOT = Path(__file__).resolve().parent

DRAFT = "https://json-schema.org/draft/2020-12/schema"

COVERAGE_PATTERN = re.compile(
    r"^test_(?:gate|adversarial)\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$"
)

REQUIRED_CATEGORIES = {
    "effect",
    "confirmation",
    "annotation",
    "token",
    "output",
    "secret",
    "timeout",
    "ratelimit",
    "sizecap",
    "degraded",
}

FIXTURE_ROOT_KEYS = {
    "schemaVersion",
    "syntheticOnly",
    "kind",
    "authorityBoundary",
    "coverage",
    "cases",
}


def _load_schema(name: str) -> dict:
    schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
    if schema.get("$schema") != DRAFT:
        raise AssertionError(f"{name} has the wrong JSON Schema draft")
    if schema.get("additionalProperties") is not False:
        raise AssertionError(f"{name} root must reject unknown fields")
    return schema


def _enum(schema: dict, pointer: tuple) -> set:
    node = schema
    for key in pointer:
        node = node[key]
    return set(node["enum"])


def verify_schema_enum_lockstep() -> None:
    schemas = sorted((ROOT / "schemas").glob("*.schema.json"))
    if len(schemas) < 2:
        raise AssertionError("expected the complete versioned schema set")

    manifest_schema = _load_schema("risk-manifest-1.0.schema.json")
    tool_props = manifest_schema["$defs"]["tool"]["properties"]
    if tool_props["effect"]["enum"] and set(tool_props["effect"]["enum"]) != {
        effect.value for effect in ToolEffect
    }:
        raise AssertionError("manifest schema and ToolEffect enum drifted")
    if set(tool_props["reversibility"]["enum"]) != {
        item.value for item in Reversibility
    }:
        raise AssertionError("manifest schema and Reversibility enum drifted")
    if set(tool_props["annotationHandling"]["enum"]) != {
        item.value for item in AnnotationHandling
    }:
        raise AssertionError("manifest schema and AnnotationHandling enum drifted")
    if set(tool_props["outputSanitization"]["enum"]) != {
        item.value for item in Posture
    }:
        raise AssertionError("manifest schema and Posture enum drifted (output)")
    if set(manifest_schema["properties"]["tokenPosture"]["enum"]) != {
        item.value for item in TokenPosture
    }:
        raise AssertionError("manifest schema and TokenPosture enum drifted")
    if set(manifest_schema["properties"]["secretLogPosture"]["enum"]) != {
        item.value for item in Posture
    }:
        raise AssertionError("manifest schema and Posture enum drifted (secret)")
    if set(manifest_schema["properties"]["degradedBehavior"]["enum"]) != {
        item.value for item in DegradedBehavior
    }:
        raise AssertionError("manifest schema and DegradedBehavior enum drifted")

    report_schema = _load_schema("gate-report-1.0.schema.json")
    finding_props = report_schema["$defs"]["finding"]["properties"]
    if set(finding_props["checkId"]["enum"]) != {item.value for item in CheckId}:
        raise AssertionError("report schema and CheckId enum drifted")
    if set(finding_props["verdict"]["enum"]) != {item.value for item in Verdict}:
        raise AssertionError("report schema and Verdict enum drifted")
    if set(finding_props["reasonCode"]["enum"]) != {item.value for item in ReasonCode}:
        raise AssertionError("report schema and ReasonCode enum drifted")
    if set(report_schema["properties"]["disposition"]["enum"]) != {
        item.value for item in Disposition
    }:
        raise AssertionError("report schema and Disposition enum drifted")


def _resolve_coverage_test(test_name: str) -> None:
    if not COVERAGE_PATTERN.fullmatch(test_name):
        raise AssertionError(f"fixture coverage must name package test methods: {test_name}")
    module_name, class_name, method_name = test_name.split(".")
    module = importlib.import_module(f"{__package__}.tests.{module_name}")
    test_class = getattr(module, class_name, None)
    test_method = getattr(test_class, method_name, None)
    if not callable(test_method):
        raise AssertionError(f"fixture coverage test is not executable: {test_name}")


def _verify_fixture(path: Path, *, adversarial: bool) -> set:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if set(fixture) != FIXTURE_ROOT_KEYS:
        raise AssertionError(f"{path.name} has unknown root fields")
    if fixture["schemaVersion"] != "1.0" or fixture["syntheticOnly"] is not True:
        raise AssertionError(f"{path.name} must be versioned and synthetic-only")
    if fixture["authorityBoundary"] != "manifest-is-static-data":
        raise AssertionError(f"{path.name} declares the wrong authority boundary")

    cases = fixture["cases"]
    ids = [case["id"] for case in cases]
    if not ids or len(ids) != len(set(ids)):
        raise AssertionError(f"{path.name} case IDs must be unique and non-empty")
    if set(fixture["coverage"]) != set(ids):
        raise AssertionError(f"{path.name} coverage must map every synthetic case")
    for test_name in set(fixture["coverage"].values()):
        _resolve_coverage_test(test_name)

    check_ids = {item.value for item in CheckId}
    reason_codes = {item.value for item in ReasonCode}
    categories = set()
    for case in cases:
        categories.add(case["category"])
        # Each synthetic manifest must parse and evaluate deterministically.
        manifest = RiskManifest.from_contract_dict(case["manifest"])
        report = evaluate(manifest)
        if report.disposition.value != case["expectedDisposition"]:
            raise AssertionError(f"{case['id']} disposition drifted from fixture")
        if adversarial:
            expected_keys = {
                "id",
                "category",
                "expectedDisposition",
                "expectedSubjectKind",
                "expectedCheck",
                "expectedReason",
                "manifest",
            }
            if set(case) != expected_keys:
                raise AssertionError(f"{case['id']} has unknown fields")
            if case["expectedCheck"] not in check_ids:
                raise AssertionError(f"{case['id']} names an unknown check")
            if case["expectedReason"] not in reason_codes:
                raise AssertionError(f"{case['id']} names an unknown reason code")
            if case["expectedSubjectKind"] not in {"server", "tool"}:
                raise AssertionError(f"{case['id']} has an unknown subject kind")
            if report.disposition is not Disposition.BLOCK:
                raise AssertionError(f"{case['id']} must fail closed")
        else:
            if set(case) != {"id", "category", "expectedDisposition", "manifest"}:
                raise AssertionError(f"{case['id']} has unknown fields")
            if report.disposition is not Disposition.ALLOW:
                raise AssertionError(f"{case['id']} must pass cleanly")
    return categories


def verify_fixtures() -> None:
    adversarial_categories = _verify_fixture(
        ROOT / "fixtures" / "adversarial-servers.synthetic.json", adversarial=True
    )
    if adversarial_categories != REQUIRED_CATEGORIES:
        raise AssertionError("adversarial corpus is missing a failure-mode category")
    clean_categories = _verify_fixture(
        ROOT / "fixtures" / "clean-servers.synthetic.json", adversarial=False
    )
    if clean_categories != {"clean"}:
        raise AssertionError("clean corpus must contain only clean cases")


def verify_contract_artifacts() -> None:
    verify_schema_enum_lockstep()
    verify_fixtures()
    findings = scan()
    if findings:
        raise AssertionError("; ".join(findings))


def main() -> int:
    verify_contract_artifacts()
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        [
            "tools.mcp_security_gate.tests.test_gate",
            "tools.mcp_security_gate.tests.test_checks",
            "tools.mcp_security_gate.tests.test_adversarial",
        ]
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1
    print("mcp_security_gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
