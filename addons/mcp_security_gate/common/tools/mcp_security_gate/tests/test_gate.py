from __future__ import annotations

import unittest

from ..checks import SERVER_CHECKS, TOOL_CHECKS
from ..contracts import (
    AnnotationHandling,
    CheckId,
    Disposition,
    Posture,
    Reversibility,
    RiskManifest,
    ToolEffect,
    Verdict,
)
from ..gate import evaluate, evaluate_contract_dict
from .common import load_fixture, manifest, tool


class GateContractTests(unittest.TestCase):
    def test_fully_clean_manifest_allows_with_no_fail(self) -> None:
        report = evaluate(manifest())
        self.assertIs(report.disposition, Disposition.ALLOW)
        self.assertTrue(report.fail_closed)
        self.assertFalse([f for f in report.findings if f.verdict is Verdict.FAIL])

    def test_every_check_runs_once_per_subject(self) -> None:
        two_tools = (tool(tool_id="tool-a"), tool(tool_id="tool-b"))
        report = evaluate(manifest(tools=two_tools))
        expected = len(SERVER_CHECKS) + len(TOOL_CHECKS) * len(two_tools)
        self.assertEqual(len(report.findings), expected)
        seen_checks = {finding.check_id for finding in report.findings}
        self.assertEqual(seen_checks, set(CheckId))

    def test_single_failure_forces_block_fail_closed(self) -> None:
        # One unknown posture anywhere must block the whole server.
        report = evaluate(manifest(tools=(tool(output_sanitization=Posture.UNKNOWN),)))
        self.assertIs(report.disposition, Disposition.BLOCK)
        fails = [f for f in report.findings if f.verdict is Verdict.FAIL]
        self.assertEqual(len(fails), 1)
        self.assertIs(fails[0].check_id, CheckId.OUTPUT_SANITIZATION)

    def test_not_applicable_alone_never_blocks_and_never_allows_on_its_own(self) -> None:
        report = evaluate(manifest())
        verdicts = {f.verdict for f in report.findings}
        self.assertIn(Verdict.NOT_APPLICABLE, verdicts)
        self.assertIs(report.disposition, Disposition.ALLOW)

    def test_report_round_trips_through_contract_dict(self) -> None:
        report = evaluate(manifest())
        payload = report.to_contract_dict()
        self.assertEqual(payload["schemaVersion"], "1.0")
        self.assertEqual(payload["disposition"], "allow")
        self.assertTrue(payload["failClosed"])
        self.assertEqual(len(payload["findings"]), len(report.findings))

    def test_manifest_round_trips_and_evaluates_identically(self) -> None:
        original = manifest(
            tools=(
                tool(
                    effect=ToolEffect.DESTRUCTIVE,
                    reversibility=Reversibility.IRREVERSIBLE,
                    requires_confirmation=True,
                ),
            )
        )
        reparsed = RiskManifest.from_contract_dict(original.to_contract_dict())
        self.assertEqual(reparsed, original)
        self.assertEqual(
            evaluate(reparsed).to_contract_dict(), evaluate(original).to_contract_dict()
        )

    def test_clean_manifest_allows(self) -> None:
        fixture = load_fixture("clean-servers.synthetic.json")
        self.assertEqual(fixture["kind"], "clean")
        self.assertTrue(fixture["cases"])
        for case in fixture["cases"]:
            with self.subTest(case=case["id"]):
                report = evaluate_contract_dict(case["manifest"])
                self.assertEqual(report.disposition.value, case["expectedDisposition"])
                self.assertIs(report.disposition, Disposition.ALLOW)
                self.assertFalse(
                    [f for f in report.findings if f.verdict is Verdict.FAIL]
                )

    def test_trusted_annotations_block_even_on_read_only_tool(self) -> None:
        report = evaluate(
            manifest(
                tools=(
                    tool(annotation_handling=AnnotationHandling.TRUSTED_AS_INSTRUCTIONS),
                )
            )
        )
        self.assertIs(report.disposition, Disposition.BLOCK)


if __name__ == "__main__":
    unittest.main()
