from __future__ import annotations

import json
from pathlib import Path
import unittest

from ..contracts import ClaimState, Purpose
from ..egress import build_egress
from ..reducer import reduce_claims
from .common import claim


SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "schemas"
        / "egress-payload-1.0.schema.json"
    ).read_text(encoding="utf-8")
)


def _released_paths(payload) -> set[str]:
    return {field["fieldPath"] for field in payload["fields"]}


def _dropped(payload) -> dict[str, str]:
    return {item["fieldPath"]: item["code"] for item in payload["droppedFieldPaths"]}


class EgressTests(unittest.TestCase):
    def _egress(self, claims, requested, **kwargs):
        reductions = reduce_claims(claims)
        params = {"purpose": Purpose.TREATMENT, "recipient_id": "recipient-ehr"}
        params.update(kwargs)
        return build_egress(requested, reductions, **params)

    def test_confirmed_and_requested_is_released(self) -> None:
        payload = self._egress(
            [claim(field_path="a.one", state=ClaimState.CONFIRMED, value="v1")],
            ["a.one"],
        )
        self.assertEqual(_released_paths(payload), {"a.one"})
        self.assertEqual(payload["fields"][0]["value"], "v1")
        self.assertEqual(payload["fields"][0]["decisionState"], "confirmed")
        self.assertEqual(payload["fieldCount"], 1)

    def test_corrected_and_requested_is_released(self) -> None:
        payload = self._egress(
            [
                claim(
                    claim_id="claim-a",
                    field_path="a.one",
                    state=ClaimState.CONFIRMED,
                    value="old",
                    sequence=0,
                ),
                claim(
                    claim_id="claim-b",
                    field_path="a.one",
                    state=ClaimState.CORRECTED,
                    value="new",
                    sequence=1,
                ),
            ],
            ["a.one"],
        )
        self.assertEqual(payload["fields"][0]["value"], "new")
        self.assertEqual(payload["fields"][0]["decisionState"], "corrected")

    def test_confirmed_but_not_requested_never_leaves(self) -> None:
        payload = self._egress(
            [
                claim(field_path="a.one", claim_id="claim-a", state=ClaimState.CONFIRMED),
                claim(field_path="b.two", claim_id="claim-b", state=ClaimState.CONFIRMED),
            ],
            ["a.one"],
        )
        self.assertEqual(_released_paths(payload), {"a.one"})
        self.assertNotIn("b.two", _released_paths(payload))
        self.assertNotIn("b.two", _dropped(payload))

    def test_proposed_requested_is_dropped(self) -> None:
        payload = self._egress(
            [claim(field_path="a.one", state=ClaimState.PROPOSED)],
            ["a.one"],
        )
        self.assertEqual(_released_paths(payload), set())
        self.assertEqual(_dropped(payload)["a.one"], "dropped-not-releasable")

    def test_requested_without_claim_is_dropped(self) -> None:
        payload = self._egress([], ["a.one"])
        self.assertEqual(_dropped(payload)["a.one"], "dropped-no-decision")

    def test_purpose_mismatch_is_dropped(self) -> None:
        payload = self._egress(
            [
                claim(
                    field_path="a.one",
                    state=ClaimState.CONFIRMED,
                    purpose=Purpose.RESEARCH,
                )
            ],
            ["a.one"],
            purpose=Purpose.TREATMENT,
        )
        self.assertEqual(_dropped(payload)["a.one"], "dropped-purpose-mismatch")

    def test_recipient_mismatch_is_dropped(self) -> None:
        payload = self._egress(
            [
                claim(
                    field_path="a.one",
                    state=ClaimState.CONFIRMED,
                    recipient_id="recipient-other",
                )
            ],
            ["a.one"],
            recipient_id="recipient-ehr",
        )
        self.assertEqual(_dropped(payload)["a.one"], "dropped-recipient-mismatch")

    def test_payload_matches_schema_shape(self) -> None:
        payload = self._egress(
            [claim(field_path="a.one", state=ClaimState.CONFIRMED)],
            ["a.one"],
        )
        self.assertEqual(set(payload), set(SCHEMA["required"]))
        self.assertRegex(payload["payloadDigest"], r"^sha256:[0-9a-f]{64}$")
        field_keys = set(
            SCHEMA["properties"]["fields"]["items"]["required"]
        )
        self.assertEqual(set(payload["fields"][0]), field_keys)


if __name__ == "__main__":
    unittest.main()
