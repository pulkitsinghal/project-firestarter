from __future__ import annotations

import unittest

from ..contracts import ClaimState, ExtractionClaim, Purpose
from ..egress import build_egress
from ..reducer import reduce_claims
from .common import claim


class AdversarialTests(unittest.TestCase):
    def test_unknown_state_is_rejected(self) -> None:
        contract = claim(state=ClaimState.CONFIRMED).to_contract_dict()
        contract["state"] = "trust-me"
        with self.assertRaises(ValueError):
            ExtractionClaim.from_contract_dict(contract)

    def test_unknown_claim_field_is_rejected(self) -> None:
        contract = claim(state=ClaimState.CONFIRMED).to_contract_dict()
        contract["injectedAuthority"] = "release-everything"
        with self.assertRaises(ValueError):
            ExtractionClaim.from_contract_dict(contract)

    def test_duplicate_claim_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            reduce_claims(
                [
                    claim(claim_id="dup", field_path="a.one"),
                    claim(claim_id="dup", field_path="b.two"),
                ]
            )

    def test_conflicted_field_never_egresses(self) -> None:
        reductions = reduce_claims(
            [
                claim(
                    claim_id="claim-a",
                    field_path="a.one",
                    state=ClaimState.CONFIRMED,
                    value="x",
                    sequence=0,
                ),
                claim(
                    claim_id="claim-b",
                    field_path="a.one",
                    state=ClaimState.CONFIRMED,
                    value="y",
                    sequence=1,
                ),
            ]
        )
        payload = build_egress(
            ["a.one"],
            reductions,
            purpose=Purpose.TREATMENT,
            recipient_id="recipient-ehr",
        )
        self.assertEqual(payload["fields"], [])
        self.assertEqual(
            payload["droppedFieldPaths"][0]["code"], "dropped-not-releasable"
        )

    def test_egress_ignores_paths_absent_from_reductions(self) -> None:
        # The builder only ever reads reductions the pure reducer produced; a
        # caller cannot smuggle a value in by naming an unreduced path.
        payload = build_egress(
            ["ghost.field"],
            {},
            purpose=Purpose.TREATMENT,
            recipient_id="recipient-ehr",
        )
        self.assertEqual(payload["fields"], [])
        self.assertEqual(
            payload["droppedFieldPaths"][0]["code"], "dropped-no-decision"
        )

    def test_control_characters_in_value_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            claim(value="line\nbreak")

    def test_inverted_offsets_are_rejected_at_construction(self) -> None:
        from ..contracts import EvidenceRef

        with self.assertRaises(ValueError):
            EvidenceRef(
                source_id="source-a",
                source_digest="sha256:" + "0" * 64,
                start_offset=10,
                end_offset=5,
            )


if __name__ == "__main__":
    unittest.main()
