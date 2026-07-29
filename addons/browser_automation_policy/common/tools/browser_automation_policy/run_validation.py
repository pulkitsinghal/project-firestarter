"""Hermetic package validation entrypoint."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import re
import unittest

from .contracts import (
    ActionKind,
    AdapterKind,
    DecisionCode,
    EffectClass,
    LedgerStatus,
)
from .privacy_scan import scan


ROOT = Path(__file__).resolve().parent


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
    evidence_codes = set(
        parsed_schemas["evidence-envelope-1.0.schema.json"]["properties"][
            "decisionCode"
        ]["enum"]
    )
    if evidence_codes != {code.value for code in DecisionCode}:
        raise AssertionError("evidence schema and DecisionCode enum drifted")
    proposal_properties = parsed_schemas[
        "action-proposal-1.0.schema.json"
    ]["properties"]
    if set(proposal_properties["action"]["enum"]) != {
        action.value for action in ActionKind
    }:
        raise AssertionError("action proposal schema and ActionKind enum drifted")
    if set(proposal_properties["effect"]["enum"]) != {
        effect.value for effect in EffectClass
    }:
        raise AssertionError("action proposal schema and EffectClass enum drifted")
    if set(proposal_properties["adapter"]["enum"]) != {
        adapter.value for adapter in AdapterKind
    }:
        raise AssertionError("action proposal schema and AdapterKind enum drifted")
    grant_target_properties = parsed_schemas[
        "capability-grant-1.0.schema.json"
    ]["properties"]["allowedActionTargets"]["items"]["properties"]
    if set(grant_target_properties["action"]["enum"]) != {
        action.value for action in ActionKind
    }:
        raise AssertionError("capability grant schema and ActionKind enum drifted")
    if set(grant_target_properties["effect"]["enum"]) != {
        effect.value for effect in EffectClass
    }:
        raise AssertionError("capability grant schema and EffectClass enum drifted")
    if set(grant_target_properties["adapter"]["enum"]) != {
        adapter.value for adapter in AdapterKind
    }:
        raise AssertionError("capability grant schema and AdapterKind enum drifted")
    if set(grant_target_properties["targetKind"]["enum"]) != {
        "semantic",
        "relative-region",
        "remote-region",
    }:
        raise AssertionError("capability grant target kinds drifted")
    ledger_statuses = set(
        parsed_schemas["action-ledger-record-1.0.schema.json"]["properties"][
            "status"
        ]["enum"]
    )
    if ledger_statuses != {status.value for status in LedgerStatus}:
        raise AssertionError("ledger schema and LedgerStatus enum drifted")

    fixture = json.loads(
        (ROOT / "fixtures" / "adversarial-scenarios.synthetic.json").read_text(
            encoding="utf-8"
        )
    )
    if fixture != {
        "schemaVersion": fixture.get("schemaVersion"),
        "syntheticOnly": fixture.get("syntheticOnly"),
        "authorityBoundary": fixture.get("authorityBoundary"),
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
        r"^test_(?:policy|adversarial)\.[A-Za-z0-9_]+"
        r"\.[A-Za-z0-9_]+$"
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
    required_categories = {
        "semantic",
        "lifecycle",
        "frame",
        "shadow",
        "geometry",
        "injection",
        "ledger",
        "citrix",
        "voice",
    }
    if {scenario["category"] for scenario in scenarios} != required_categories:
        raise AssertionError("fixture corpus is missing an adversarial category")
    reason_codes = {code.value for code in DecisionCode}
    for scenario in scenarios:
        if set(scenario) != {
            "id",
            "category",
            "transition",
            "expectedCode",
            "expectedEffects",
        }:
            raise AssertionError(f"{scenario['id']} has unknown fields")
        if scenario["expectedCode"] not in reason_codes:
            raise AssertionError(f"{scenario['id']} has an unknown reason code")
        if scenario["expectedEffects"] != 0:
            raise AssertionError(f"{scenario['id']} must remain effect-free")

    findings = scan()
    if findings:
        raise AssertionError("; ".join(findings))


def main() -> int:
    verify_contract_artifacts()
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        [
            "tools.browser_automation_policy.tests.test_policy",
            "tools.browser_automation_policy.tests.test_adversarial",
        ]
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1
    print("browser-automation-policy: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
