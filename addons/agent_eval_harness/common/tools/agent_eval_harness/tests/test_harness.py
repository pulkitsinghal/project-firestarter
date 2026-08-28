from __future__ import annotations

import unittest

from ..contracts import CheckKind, ResultState
from ..harness import evaluate
from . import common


class HarnessReducerTests(unittest.TestCase):
    def _vector(self, vector_id: str) -> dict:
        for vector in common.load_case_vectors():
            if vector["id"] == vector_id:
                return vector
        raise AssertionError(f"missing synthetic vector {vector_id}")

    def _run(self, vector: dict) -> ResultState:
        result = evaluate(
            vector["case"], vector["candidate"], vector["input_fixtures"]
        )
        return result.state

    def test_all_blocking_satisfied_passes(self) -> None:
        vector = self._vector("SC-PASS")
        self.assertEqual(self._run(vector).value, vector["expected_state"])
        self.assertEqual(self._run(vector), ResultState.PASSED)

    def test_blocking_violation_fails(self) -> None:
        vector = self._vector("SC-FAIL")
        self.assertEqual(self._run(vector), ResultState.FAILED)

    def test_non_blocking_signal_needs_review(self) -> None:
        vector = self._vector("SC-REVIEW")
        # The blocking check is satisfied; only the non-blocking regex fails.
        self.assertEqual(self._run(vector), ResultState.NEEDS_REVIEW)

    def test_missing_input_fixture_is_unavailable(self) -> None:
        vector = self._vector("SC-INPUT-MISSING")
        self.assertEqual(self._run(vector), ResultState.UNAVAILABLE)

    def test_result_digest_is_canonical(self) -> None:
        vector = self._vector("SC-PASS")
        result = evaluate(
            vector["case"], vector["candidate"], vector["input_fixtures"]
        )
        contract = result.to_contract_dict()
        # The digest is content-addressed over the scored payload and stable
        # across repeated evaluation of the same inputs.
        again = evaluate(
            vector["case"], vector["candidate"], vector["input_fixtures"]
        )
        self.assertEqual(contract["resultDigest"], again.to_contract_dict()["resultDigest"])
        self.assertTrue(contract["resultDigest"].startswith("sha256:"))
        self.assertEqual(result.state, ResultState.PASSED)

    def test_case_candidate_id_mismatch_fails_closed(self) -> None:
        a_case = common.case(case_id="case-x")
        wrong = common.candidate(case_id="case-y")
        with self.assertRaises(ValueError):
            evaluate(a_case, wrong, common.input_fixtures_for(a_case, {"seed": 1}))

    def test_non_blocking_only_never_fails(self) -> None:
        # A case with a single non-blocking violated check yields needs_review,
        # never failed: blocking checks alone decide pass/fail.
        chk = common.check(kind=CheckKind.EXACT_EQUALS, blocking=False,
                           params={"expected": "north"})
        cand = common.candidate(
            evidence_items=(common.evidence(values={"answer": "south"}),)
        )
        matched_case = common.case(
            checks=(chk,),
            input_fixture_digest=common.canonical_digest({"s": 1}),
        )
        result = evaluate(
            matched_case, cand, common.input_fixtures_for(matched_case, {"s": 1})
        )
        self.assertEqual(result.state, ResultState.NEEDS_REVIEW)


if __name__ == "__main__":
    unittest.main()
