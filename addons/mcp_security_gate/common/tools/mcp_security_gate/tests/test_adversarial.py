from __future__ import annotations

import unittest

from ..contracts import Disposition, Verdict
from ..gate import evaluate_contract_dict
from .common import load_fixture


# Every failure mode named in the task spec, mapped to the fixture category and
# the exact reason code the gate must emit. This is the executable side of the
# fixture coverage map.
EXPECTED_MODES = {
    "effect": {"effect-reversibility-mismatch", "effect-undeclared"},
    "confirmation": {"confirmation-missing-for-irreversible"},
    "annotation": {"annotations-trusted-as-instructions", "annotation-posture-unknown"},
    "token": {
        "token-blind-passthrough",
        "token-audience-mismatch",
        "token-posture-unknown",
    },
    "output": {"output-unsanitized"},
    "secret": {"secret-in-logs"},
    "timeout": {"timeout-absent"},
    "ratelimit": {"rate-limit-absent"},
    "sizecap": {"size-cap-absent"},
    "degraded": {"degraded-fails-open", "degraded-posture-unknown"},
}


class AdversarialGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = load_fixture("adversarial-servers.synthetic.json")

    def _subject_id(self, case: dict) -> str:
        manifest = case["manifest"]
        if case["expectedSubjectKind"] == "server":
            return manifest["serverId"]
        return manifest["tools"][0]["toolId"]

    def test_targeted_failure_blocks_fail_closed(self) -> None:
        cases = self.fixture["cases"]
        self.assertTrue(cases)
        for case in cases:
            with self.subTest(case=case["id"]):
                report = evaluate_contract_dict(case["manifest"])
                # Fail-closed disposition on the targeted defect.
                self.assertIs(report.disposition, Disposition.BLOCK)
                self.assertEqual(
                    report.disposition.value, case["expectedDisposition"]
                )
                fails = [f for f in report.findings if f.verdict is Verdict.FAIL]
                # The synthetic manifest is otherwise clean: exactly one defect.
                self.assertEqual(len(fails), 1, [f.reason_code.value for f in fails])
                finding = fails[0]
                self.assertEqual(finding.check_id.value, case["expectedCheck"])
                self.assertEqual(finding.subject_id, self._subject_id(case))
                self.assertEqual(finding.reason_code.value, case["expectedReason"])

    def test_all_failure_modes_are_covered(self) -> None:
        by_category: dict[str, set[str]] = {}
        for case in self.fixture["cases"]:
            by_category.setdefault(case["category"], set()).add(case["expectedReason"])
        self.assertEqual(by_category, EXPECTED_MODES)

    def test_no_adversarial_manifest_declares_an_endpoint_or_secret(self) -> None:
        # Fixtures are static data only: opaque ids and closed enums, never a
        # real server address, token, or credential.
        blob = repr(self.fixture)
        self.assertNotIn("://", blob)
        for banned in ("http", "token=", "password", "secret=", "@"):
            self.assertNotIn(banned, blob)


if __name__ == "__main__":
    unittest.main()
