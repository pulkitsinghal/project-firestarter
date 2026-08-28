from __future__ import annotations

import json
from pathlib import Path
import unittest

from ..contracts import ClaimState, ReductionCode
from ..reducer import reduce_claims
from .common import claim


PATH = "encounter.chief-complaint"


class ReducerTests(unittest.TestCase):
    def _reduce(self, *claims):
        return reduce_claims(claims)[PATH]

    def test_confirmed_reduces_to_releasable(self) -> None:
        decision = self._reduce(claim(state=ClaimState.CONFIRMED, value="value-token-a"))
        self.assertEqual(decision.outcome, ReductionCode.RELEASABLE_CONFIRMED)
        self.assertEqual(decision.released_value, "value-token-a")
        self.assertEqual(decision.winning_claim_id, "claim-a")
        self.assertTrue(decision.is_releasable)

    def test_proposed_only_is_withheld(self) -> None:
        decision = self._reduce(claim(state=ClaimState.PROPOSED))
        self.assertEqual(decision.outcome, ReductionCode.WITHHELD_PROPOSED)
        self.assertIsNone(decision.released_value)

    def test_unknown_is_withheld(self) -> None:
        decision = self._reduce(claim(state=ClaimState.UNKNOWN))
        self.assertEqual(decision.outcome, ReductionCode.WITHHELD_UNKNOWN)

    def test_omitted_is_withheld(self) -> None:
        decision = self._reduce(claim(state=ClaimState.OMITTED))
        self.assertEqual(decision.outcome, ReductionCode.WITHHELD_OMITTED)

    def test_corrected_overrides_confirmed(self) -> None:
        decision = self._reduce(
            claim(claim_id="claim-a", state=ClaimState.CONFIRMED, value="old", sequence=0),
            claim(
                claim_id="claim-b",
                state=ClaimState.CORRECTED,
                value="new",
                sequence=1,
            ),
        )
        self.assertEqual(decision.outcome, ReductionCode.RELEASABLE_CORRECTED)
        self.assertEqual(decision.released_value, "new")
        self.assertEqual(decision.winning_claim_id, "claim-b")

    def test_supersedes_link_activates_newer(self) -> None:
        decision = self._reduce(
            claim(claim_id="claim-a", state=ClaimState.CONFIRMED, value="old", sequence=0),
            claim(
                claim_id="claim-b",
                state=ClaimState.CONFIRMED,
                value="new",
                sequence=1,
                supersedes=("claim-a",),
            ),
        )
        self.assertEqual(decision.outcome, ReductionCode.RELEASABLE_CONFIRMED)
        self.assertEqual(decision.released_value, "new")
        self.assertEqual(decision.winning_claim_id, "claim-b")
        self.assertIn("claim-a", decision.superseded_claim_ids)

    def test_all_superseded_is_withheld(self) -> None:
        decision = self._reduce(claim(claim_id="claim-a", state=ClaimState.SUPERSEDED))
        self.assertEqual(decision.outcome, ReductionCode.WITHHELD_SUPERSEDED)

    def test_two_confirmed_disagree_conflict(self) -> None:
        decision = self._reduce(
            claim(claim_id="claim-a", state=ClaimState.CONFIRMED, value="x", sequence=0),
            claim(claim_id="claim-b", state=ClaimState.CONFIRMED, value="y", sequence=1),
        )
        self.assertEqual(decision.outcome, ReductionCode.WITHHELD_CONFLICTED)
        self.assertIsNone(decision.released_value)

    def test_two_corrected_disagree_conflict(self) -> None:
        decision = self._reduce(
            claim(claim_id="claim-a", state=ClaimState.CORRECTED, value="x", sequence=2),
            claim(claim_id="claim-b", state=ClaimState.CORRECTED, value="y", sequence=3),
        )
        self.assertEqual(decision.outcome, ReductionCode.WITHHELD_CONFLICTED)

    def test_explicit_conflicted_withholds(self) -> None:
        decision = self._reduce(
            claim(claim_id="claim-a", state=ClaimState.CONFIRMED, value="x", sequence=0),
            claim(claim_id="claim-b", state=ClaimState.CONFLICTED, value="x", sequence=1),
        )
        self.assertEqual(decision.outcome, ReductionCode.WITHHELD_CONFLICTED)

    def test_reduction_is_deterministic_and_ordered(self) -> None:
        claims = [
            claim(claim_id="claim-b", field_path="b.two", state=ClaimState.CONFIRMED),
            claim(claim_id="claim-a", field_path="a.one", state=ClaimState.CONFIRMED),
        ]
        first = reduce_claims(list(claims))
        second = reduce_claims(list(reversed(claims)))
        self.assertEqual(list(first), ["a.one", "b.two"])
        self.assertEqual(
            {path: decision.outcome for path, decision in first.items()},
            {path: decision.outcome for path, decision in second.items()},
        )

    def test_decision_round_trips_through_schema_keys(self) -> None:
        decision = self._reduce(claim(state=ClaimState.CORRECTED, value="v"))
        contract = decision.to_contract_dict()
        schema = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "schemas"
                / "reduced-decision-1.0.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(set(contract), set(schema["required"]))


if __name__ == "__main__":
    unittest.main()
