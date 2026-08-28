from __future__ import annotations

import unittest

from ..contracts import (
    CandidateOutput,
    Check,
    CheckKind,
    CritiqueVerdict,
    EvalCase,
    ResultState,
)
from ..harness import evaluate
from . import common


class AdversarialTests(unittest.TestCase):
    def test_digest_mismatch_makes_evidence_unavailable(self) -> None:
        vector = next(
            v for v in common.load_case_vectors() if v["id"] == "SC-DIGEST-MISMATCH"
        )
        result = evaluate(
            vector["case"], vector["candidate"], vector["input_fixtures"]
        )
        # Tampered evidence digest -> blocking check unavailable -> unavailable.
        self.assertEqual(result.state, ResultState.UNAVAILABLE)
        self.assertFalse(result.evidence_verified)

    def test_missing_evidence_field_is_unavailable(self) -> None:
        cand = common.candidate(
            evidence_items=(common.evidence(values={"other": "north"}),)
        )
        # Digest verifies but the referenced field ("answer") is absent.
        matched_case = common.case(
            input_fixture_digest=common.canonical_digest({"seed": 1})
        )
        result = evaluate(
            matched_case, cand, common.input_fixtures_for(matched_case, {"seed": 1})
        )
        self.assertEqual(result.state, ResultState.UNAVAILABLE)
        self.assertTrue(result.evidence_verified)

    def test_advisory_critique_cannot_flip_verdict(self) -> None:
        # A failing case with an advisory critique claiming "pass" stays failed,
        # and stripping/altering the critique never changes the verdict.
        vector = next(
            v for v in common.load_case_vectors() if v["id"] == "SC-CRITIQUE-CANNOT-FLIP"
        )
        base = evaluate(vector["case"], vector["candidate"], vector["input_fixtures"])
        self.assertEqual(base.state, ResultState.FAILED)
        self.assertTrue(base.advisory_critique_recorded)

        no_critique = common.candidate(
            case_id=vector["candidate"].case_id,
            evidence_items=vector["candidate"].evidence,
            critique=None,
        )
        stripped = evaluate(vector["case"], no_critique, vector["input_fixtures"])
        self.assertEqual(stripped.state, ResultState.FAILED)
        self.assertFalse(stripped.advisory_critique_recorded)

        for verdict in CritiqueVerdict:
            flipped = common.candidate(
                case_id=vector["candidate"].case_id,
                evidence_items=vector["candidate"].evidence,
                critique=common.critique(verdict=verdict),
            )
            self.assertEqual(
                evaluate(vector["case"], flipped, vector["input_fixtures"]).state,
                ResultState.FAILED,
                f"critique verdict {verdict.value} must not flip the verdict",
            )

    def test_unknown_check_kind_is_rejected(self) -> None:
        raw = common.case().to_contract_dict()
        raw["checks"][0]["kind"] = "vibes-match"
        with self.assertRaises(ValueError):
            EvalCase.from_contract_dict(raw)

    def test_unknown_field_is_rejected(self) -> None:
        raw_case = common.case().to_contract_dict()
        raw_case["surpriseField"] = 1
        with self.assertRaises(ValueError):
            EvalCase.from_contract_dict(raw_case)

        raw_candidate = common.candidate().to_contract_dict()
        raw_candidate["evidence"][0]["extra"] = "x"
        with self.assertRaises(ValueError):
            CandidateOutput.from_contract_dict(raw_candidate)

    def test_unknown_comparator_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Check(
                check_id="c1",
                kind=CheckKind.NUMERIC_THRESHOLD,
                blocking=True,
                evidence_id="e1",
                field_token="f1",
                params={"comparator": "approximately", "bound": 5},
            )

    def test_no_side_effects_recorded_in_catalog(self) -> None:
        import json
        from pathlib import Path

        catalog = json.loads(
            (
                Path(__file__).resolve().parent.parent
                / "fixtures"
                / "adversarial-scenarios.synthetic.json"
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(
            all(scenario["sideEffects"] == 0 for scenario in catalog["scenarios"])
        )


if __name__ == "__main__":
    unittest.main()
