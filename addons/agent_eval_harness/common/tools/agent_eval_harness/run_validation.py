"""Hermetic package validation entrypoint.

Verifies that the versioned JSON schemas parse, use the right draft, reject
unknown fields, and stay in lockstep with the closed contract enums; that the
synthetic fixtures are versioned, synthetic-only, and map every scenario to an
executable test; runs the static privacy scan; then runs the unittest suites.
Uses only the Python standard library, no network, and no dynamic import of a
caller-named module.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

from .contracts import (
    CheckKind,
    CheckOutcome,
    CritiqueVerdict,
    NumericComparator,
    ResultState,
)
from .privacy_scan import scan
from .tests import test_adversarial, test_checks, test_harness


ROOT = Path(__file__).resolve().parent
DRAFT = "https://json-schema.org/draft/2020-12/schema"

# Fixed, in-package test modules keyed by the name used in the coverage map.
_TEST_MODULES = {
    "test_harness": test_harness,
    "test_checks": test_checks,
    "test_adversarial": test_adversarial,
}
_SUITE_NAMES = [
    "tools.agent_eval_harness.tests.test_harness",
    "tools.agent_eval_harness.tests.test_checks",
    "tools.agent_eval_harness.tests.test_adversarial",
]


def _load_schema(name: str) -> dict:
    schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
    if schema.get("$schema") != DRAFT:
        raise AssertionError(f"{name} has the wrong JSON Schema draft")
    if schema.get("additionalProperties") is not False:
        raise AssertionError(f"{name} root must reject unknown fields")
    return schema


def verify_schemas() -> None:
    schemas = sorted((ROOT / "schemas").glob("*.schema.json"))
    if len(schemas) < 3:
        raise AssertionError("expected the complete versioned schema set")
    case_schema = _load_schema("eval-case-1.0.schema.json")
    candidate_schema = _load_schema("eval-candidate-1.0.schema.json")
    result_schema = _load_schema("eval-result-1.0.schema.json")
    for schema in schemas:
        _load_schema(schema.name)

    check_props = case_schema["$defs"]["check"]["properties"]
    if set(check_props["kind"]["enum"]) != {kind.value for kind in CheckKind}:
        raise AssertionError("eval-case kind enum and CheckKind drifted")
    if set(case_schema["$defs"]["numericComparator"]["enum"]) != {
        comparator.value for comparator in NumericComparator
    }:
        raise AssertionError("eval-case comparator enum and NumericComparator drifted")

    verdict_enum = candidate_schema["properties"]["advisoryCritique"]["oneOf"][1][
        "properties"
    ]["verdict"]["enum"]
    if set(verdict_enum) != {verdict.value for verdict in CritiqueVerdict}:
        raise AssertionError("candidate verdict enum and CritiqueVerdict drifted")

    if set(result_schema["properties"]["state"]["enum"]) != {
        state.value for state in ResultState
    }:
        raise AssertionError("eval-result state enum and ResultState drifted")
    outcome_enum = result_schema["properties"]["checkResults"]["items"]["properties"][
        "outcome"
    ]["enum"]
    if set(outcome_enum) != {outcome.value for outcome in CheckOutcome}:
        raise AssertionError("eval-result outcome enum and CheckOutcome drifted")
    result_kind_enum = result_schema["properties"]["checkResults"]["items"][
        "properties"
    ]["kind"]["enum"]
    if set(result_kind_enum) != {kind.value for kind in CheckKind}:
        raise AssertionError("eval-result kind enum and CheckKind drifted")


def _resolve_test(test_name: str) -> None:
    module_name, class_name, method_name = test_name.split(".")
    module = _TEST_MODULES.get(module_name)
    if module is None:
        raise AssertionError(f"coverage names an unknown test module: {module_name}")
    test_class = getattr(module, class_name, None)
    test_method = getattr(test_class, method_name, None)
    if not callable(test_method):
        raise AssertionError(f"fixture coverage test is not executable: {test_name}")


def verify_fixtures() -> None:
    cases = json.loads(
        (ROOT / "fixtures" / "eval-cases.synthetic.json").read_text(encoding="utf-8")
    )
    if set(cases) != {"schemaVersion", "syntheticOnly", "authorityBoundary", "vectors"}:
        raise AssertionError("eval-cases fixture has unknown root fields")
    if cases["schemaVersion"] != "1.0" or cases["syntheticOnly"] is not True:
        raise AssertionError("eval-cases fixture must be versioned and synthetic-only")
    vector_ids = [vector["id"] for vector in cases["vectors"]]
    if len(vector_ids) != len(set(vector_ids)):
        raise AssertionError("eval-cases vector ids must be unique")
    result_states = {state.value for state in ResultState}
    for vector in cases["vectors"]:
        if vector["expectedState"] not in result_states:
            raise AssertionError(f"{vector['id']} declares an unknown state")

    catalog = json.loads(
        (ROOT / "fixtures" / "adversarial-scenarios.synthetic.json").read_text(
            encoding="utf-8"
        )
    )
    if set(catalog) != {
        "schemaVersion",
        "syntheticOnly",
        "authorityBoundary",
        "coverage",
        "scenarios",
    }:
        raise AssertionError("adversarial fixture has unknown root fields")
    if catalog["schemaVersion"] != "1.0" or catalog["syntheticOnly"] is not True:
        raise AssertionError("adversarial fixture must be versioned and synthetic-only")

    scenarios = catalog["scenarios"]
    ids = [scenario["id"] for scenario in scenarios]
    if len(ids) != len(set(ids)):
        raise AssertionError("scenario ids must be unique")
    coverage = catalog["coverage"]
    if set(coverage) != set(ids):
        raise AssertionError("each scenario must map to an executable test")
    coverage_pattern = re.compile(
        r"^test_(?:harness|checks|adversarial)\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$"
    )
    for scenario_id, test_name in coverage.items():
        if not isinstance(test_name, str) or not coverage_pattern.fullmatch(test_name):
            raise AssertionError(f"coverage for {scenario_id} is not a package test")
        _resolve_test(test_name)

    required_categories = {"scoring", "checks", "evidence", "critique", "malformed"}
    if {scenario["category"] for scenario in scenarios} != required_categories:
        raise AssertionError("adversarial catalog is missing a category")
    allowed_outcomes = result_states | {"rejected"}
    for scenario in scenarios:
        if set(scenario) != {
            "id",
            "category",
            "transition",
            "expectedOutcome",
            "sideEffects",
        }:
            raise AssertionError(f"{scenario['id']} has unknown fields")
        if scenario["expectedOutcome"] not in allowed_outcomes:
            raise AssertionError(f"{scenario['id']} has an unknown expected outcome")
        if scenario["sideEffects"] != 0:
            raise AssertionError(f"{scenario['id']} must remain effect-free")


def verify_contract_artifacts() -> None:
    verify_schemas()
    verify_fixtures()
    findings = scan()
    if findings:
        raise AssertionError("; ".join(findings))


def main() -> int:
    verify_contract_artifacts()
    suite = unittest.defaultTestLoader.loadTestsFromNames(_SUITE_NAMES)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1
    print("agent_eval_harness: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
