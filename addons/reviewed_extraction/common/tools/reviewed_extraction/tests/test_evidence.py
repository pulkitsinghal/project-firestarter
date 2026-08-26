from __future__ import annotations

import unittest

from ..contracts import EvidenceCode
from ..evidence import verify_evidence
from .common import SOURCE_BYTES, claim, digest_bytes, evidence


class EvidenceTests(unittest.TestCase):
    def test_matching_digest_and_offsets_verify(self) -> None:
        item = claim(evidence_ref=evidence(start_offset=0, end_offset=len(SOURCE_BYTES)))
        result = verify_evidence(SOURCE_BYTES, item)
        self.assertTrue(result.verified)
        self.assertEqual(result.code, EvidenceCode.VERIFIED)

    def test_digest_mismatch_is_flagged(self) -> None:
        item = claim(evidence_ref=evidence())
        result = verify_evidence(b"a-different-source-body", item)
        self.assertFalse(result.verified)
        self.assertEqual(result.code, EvidenceCode.DIGEST_MISMATCH)

    def test_offset_out_of_range_is_flagged(self) -> None:
        item = claim(
            evidence_ref=evidence(
                start_offset=0,
                end_offset=len(SOURCE_BYTES) + 25,
            )
        )
        result = verify_evidence(SOURCE_BYTES, item)
        self.assertFalse(result.verified)
        self.assertEqual(result.code, EvidenceCode.OFFSET_OUT_OF_RANGE)

    def test_result_carries_no_raw_content(self) -> None:
        item = claim(evidence_ref=evidence(end_offset=len(SOURCE_BYTES)))
        contract = verify_evidence(SOURCE_BYTES, item).to_contract_dict()
        self.assertEqual(
            set(contract),
            {"schemaVersion", "verified", "code", "sourceId", "sourceDigest"},
        )
        self.assertEqual(contract["sourceDigest"], digest_bytes())

    def test_digest_checked_before_offsets(self) -> None:
        # A substituted source with an out-of-range offset still reports the
        # digest mismatch first, never leaking offset information.
        item = claim(evidence_ref=evidence(start_offset=0, end_offset=5))
        result = verify_evidence(b"tiny", item)
        self.assertEqual(result.code, EvidenceCode.DIGEST_MISMATCH)


if __name__ == "__main__":
    unittest.main()
