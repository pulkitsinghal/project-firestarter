"""Contract for the production-hosting decision-frame doc.

``template/docs/HOSTING.md`` is the managed-SaaS-first "where to host each piece
in production" frame. It must ship in every stack, carry its four guardrails and
the decision table, cross-link the regulated-data posture, and leak no source
identity (it was generalized from a sibling).
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "template" / "docs" / "HOSTING.md"
GENERATE = ROOT / "bin" / "generate.py"
EXAMPLES = sorted((ROOT / "examples").glob("*.answers.json"))

GUARDRAILS = (
    "### 1. A free tier is not always a commercial licence",
    "### 2. Take payments through a merchant-of-record",
    "### 3. Draw the regulated-data (PHI/HIPAA) line deliberately",
    "### 4. Keep a side-product's infrastructure and billing separate",
)

# Generic provenance markers that would betray the sibling source. Keeping this
# list generic -- not a roster of the forbidden domain literals -- is deliberate:
# enumerating those terms in a public test would itself be the leak.
DISCLOSURE_MARKERS = ("github.com/", "source:")


class HostingDocContract(unittest.TestCase):
    def test_doc_states_the_managed_first_frame_and_table(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("managed commodity hosting", text)
        self.assertIn("## The default stack", text)
        # the decision table header binds the piece/host/tradeoff columns
        self.assertIn("| Piece | Default managed host | Why / the tradeoff |", text)

    def test_doc_carries_all_four_guardrails(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        for guardrail in GUARDRAILS:
            self.assertIn(guardrail, text)

    def test_phi_guardrail_cross_links_the_compliance_posture(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("BAA", text)
        self.assertIn("[COMPLIANCE_POSTURE.md](COMPLIANCE_POSTURE.md)", text)

    def test_go_live_points_at_the_hosting_doc(self) -> None:
        go_live = (ROOT / "template" / "docs" / "GO_LIVE.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("[HOSTING.md](HOSTING.md)", go_live)

    def test_doc_leaks_no_source_identity(self) -> None:
        text = DOC.read_text(encoding="utf-8").lower()
        for marker in DISCLOSURE_MARKERS:
            self.assertNotIn(marker, text)

    def test_doc_ships_in_every_stack_without_a_raw_token(self) -> None:
        self.assertTrue(EXAMPLES, "no example answers files found")
        with tempfile.TemporaryDirectory() as tmp:
            for answers in EXAMPLES:
                with self.subTest(answers=answers.name):
                    out = Path(tmp) / answers.stem
                    subprocess.run(
                        ["python3", str(GENERATE), "--values", str(answers),
                         "--output", str(out)],
                        check=True, capture_output=True, text=True,
                    )
                    stamped = out / "docs" / "HOSTING.md"
                    self.assertTrue(
                        stamped.exists(), f"{answers.name}: HOSTING.md missing"
                    )
                    self.assertNotIn("{{", stamped.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
