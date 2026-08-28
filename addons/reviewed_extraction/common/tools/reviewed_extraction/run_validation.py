"""Hermetic package validation entrypoint."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import re
import unittest

from .contracts import (
    ClaimState,
    EgressCode,
    EvidenceCode,
    Purpose,
    ReductionCode,
)
from .privacy_scan import scan


ROOT = Path(__file__).resolve().parent

REDUCE_CATEGORIES = {"reduce", "supersession", "conflict"}
EGRESS_CATEGORIES = {"egress", "purpose"}
REQUIRED_CATEGORIES = {
    "reduce",
    "supersession",
    "conflict",
    "egress",
    "purpose",
    "evidence",
    "parse",
}
RELEASABLE_OUTCOME_VALUES = {
    ReductionCode.RELEASABLE_CONFIRMED.value,
    ReductionCode.RELEASABLE_CORRECTED.value,
}


def verify_contract_artifacts() -> None:
    schemas = sorted((ROOT / "schemas").glob("*.schema.json"))
    if len(schemas) < 5:
        raise AssertionError("expected the complete versioned schema set")
    parsed_schemas = {}
    for path in schemas:
        schema = json.loads(path.read_text(encoding="utf-8"))
        parsed_schemas[path.name] = schema
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise AssertionError(f"{path.name} has the wrong JSON Schema draft")
        if schema.get("additionalProperties") is not False:
            raise AssertionError(f"{path.name} root must reject unknown fields")

    claim_properties = parsed_schemas["extraction-claim-1.0.schema.json"]["properties"]
    if set(claim_properties["state"]["enum"]) != {state.value for state in ClaimState}:
        raise AssertionError("claim schema and ClaimState enum drifted")
    if set(claim_properties["purpose"]["enum"]) != {
        purpose.value for purpose in Purpose
    }:
        raise AssertionError("claim schema and Purpose enum drifted")

    reduced_outcomes = set(
        parsed_schemas["reduced-decision-1.0.schema.json"]["properties"]["outcome"][
            "enum"
        ]
    )
    if reduced_outcomes != {code.value for code in ReductionCode}:
        raise AssertionError("reduced-decision schema and ReductionCode enum drifted")

    request_purposes = set(
        parsed_schemas["egress-request-1.0.schema.json"]["properties"]["purpose"][
            "enum"
        ]
    )
    if request_purposes != {purpose.value for purpose in Purpose}:
        raise AssertionError("egress-request schema and Purpose enum drifted")

    payload_properties = parsed_schemas["egress-payload-1.0.schema.json"]["properties"]
    released_states = set(
        payload_properties["fields"]["items"]["properties"]["decisionState"]["enum"]
    )
    if released_states != {ClaimState.CONFIRMED.value, ClaimState.CORRECTED.value}:
        raise AssertionError("egress payload releases a non-reviewed decision state")
    dropped_codes = set(
        payload_properties["droppedFieldPaths"]["items"]["properties"]["code"]["enum"]
    )
    if dropped_codes != {
        code.value for code in EgressCode if code is not EgressCode.RELEASED
    }:
        raise AssertionError("egress payload drop codes and EgressCode enum drifted")

    evidence_codes = set(
        parsed_schemas["evidence-result-1.0.schema.json"]["properties"]["code"]["enum"]
    )
    if evidence_codes != {code.value for code in EvidenceCode}:
        raise AssertionError("evidence-result schema and EvidenceCode enum drifted")

    fixture = json.loads(
        (ROOT / "fixtures" / "adversarial-claim-sets.synthetic.json").read_text(
            encoding="utf-8"
        )
    )
    if fixture != {
        "schemaVersion": fixture.get("schemaVersion"),
        "syntheticOnly": fixture.get("syntheticOnly"),
        "purposeBoundary": fixture.get("purposeBoundary"),
        "coverage": fixture.get("coverage"),
        "scenarios": fixture.get("scenarios"),
    }:
        raise AssertionError("fixture corpus has unknown root fields")
    if fixture["schemaVersion"] != "1.0" or fixture["syntheticOnly"] is not True:
        raise AssertionError("fixture corpus must be versioned and synthetic-only")

    scenarios = fixture["scenarios"]
    ids = [scenario["id"] for scenario in scenarios]
    if len(ids) != len(set(ids)):
        raise AssertionError("scenario IDs must be unique")
    coverage = fixture["coverage"]
    if set(coverage) != set(ids):
        raise AssertionError("each synthetic scenario must map to an executable test")
    coverage_pattern = re.compile(
        r"^test_(?:reducer|egress|evidence|adversarial)\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$"
    )
    if not all(
        isinstance(test_name, str) and coverage_pattern.fullmatch(test_name)
        for test_name in coverage.values()
    ):
        raise AssertionError("fixture coverage must name package test methods")
    for test_name in set(coverage.values()):
        module_name, class_name, method_name = test_name.split(".")
        module = importlib.import_module(f"{__package__}.tests.{module_name}")
        test_class = getattr(module, class_name, None)
        test_method = getattr(test_class, method_name, None)
        if not callable(test_method):
            raise AssertionError(f"fixture coverage test is not executable: {test_name}")

    if {scenario["category"] for scenario in scenarios} != REQUIRED_CATEGORIES:
        raise AssertionError("fixture corpus is missing a scenario category")

    reduce_codes = {code.value for code in ReductionCode}
    egress_codes = {code.value for code in EgressCode}
    evidence_code_values = {code.value for code in EvidenceCode}
    for scenario in scenarios:
        if set(scenario) != {
            "id",
            "category",
            "transition",
            "expectedCode",
            "expectedReleased",
        }:
            raise AssertionError(f"{scenario['id']} has unknown fields")
        category = scenario["category"]
        code = scenario["expectedCode"]
        released = scenario["expectedReleased"]
        if released not in (0, 1):
            raise AssertionError(f"{scenario['id']} released flag must be 0 or 1")
        if category in REDUCE_CATEGORIES:
            if code not in reduce_codes:
                raise AssertionError(f"{scenario['id']} has an unknown reduction code")
            expect = 1 if code in RELEASABLE_OUTCOME_VALUES else 0
        elif category in EGRESS_CATEGORIES:
            if code not in egress_codes:
                raise AssertionError(f"{scenario['id']} has an unknown egress code")
            expect = 1 if code == EgressCode.RELEASED.value else 0
        elif category == "evidence":
            if code not in evidence_code_values:
                raise AssertionError(f"{scenario['id']} has an unknown evidence code")
            expect = 0
        else:  # parse
            if code != "rejected":
                raise AssertionError(f"{scenario['id']} parse scenario must be rejected")
            expect = 0
        if released != expect:
            raise AssertionError(
                f"{scenario['id']} released flag disagrees with its code"
            )

    findings = scan()
    if findings:
        raise AssertionError("; ".join(findings))


def main() -> int:
    verify_contract_artifacts()
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        [
            "tools.reviewed_extraction.tests.test_reducer",
            "tools.reviewed_extraction.tests.test_egress",
            "tools.reviewed_extraction.tests.test_evidence",
            "tools.reviewed_extraction.tests.test_adversarial",
        ]
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1
    print("reviewed_extraction: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
