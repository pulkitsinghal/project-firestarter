"""Contract: firestarter's shipped Anthropic Messages payloads carry no sampling
parameter, and each call site documents why.

Current Claude models reject ``temperature``/``top_p``/``top_k`` with a 400, and
anthropic-version 2026-10-21 and later reject them on every model. firestarter
sends only ``model`` + ``max_tokens``; ``ai-pr-review.yml`` is a required check
that ``auto-merge`` gates on, so a sampling parameter added after a model bump
would fail every PR. This binds the two shipped payloads to that invariant.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
REVIEW_WORKFLOW = ROOT / "template" / ".github" / "workflows" / "ai-pr-review.yml"
AGENT_DROP = (
    ROOT / "addons" / "scheduled_agent" / "common" / "scripts" / "agent-drop.mjs"
)

# A sampling parameter written as a payload KEY -- `temperature:` (JS object) or
# `"temperature":` (JSON) -- never the bare word, which is all the guard comment
# uses. Binding the active key form rather than a substring is the lesson of the
# deploy-manifest gitignore assertion: match the operative rule, not prose that
# merely quotes it.
SAMPLING_KEY = re.compile(r"""["']?(temperature|top_p|top_k)["']?\s*:""")

# Each call site carries this phrase verbatim, so the documentation cannot be
# dropped while the payload stays clean.
GUARD_PHRASE = "reject sampling parameters with a 400"


class AnthropicPayloadHygiene(unittest.TestCase):
    def test_pr_review_workflow_sends_no_sampling_parameter(self) -> None:
        text = REVIEW_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('"max_tokens"', text)  # anchor: we are reading the payload
        self.assertEqual(SAMPLING_KEY.findall(text), [])
        self.assertIn(GUARD_PHRASE, text)

    def test_scheduled_agent_drop_sends_no_sampling_parameter(self) -> None:
        text = AGENT_DROP.read_text(encoding="utf-8")
        self.assertIn("max_tokens:", text)  # anchor: we are reading the payload
        self.assertEqual(SAMPLING_KEY.findall(text), [])
        self.assertIn(GUARD_PHRASE, text)

    def test_assertion_binds_the_key_not_the_guard_comment(self) -> None:
        # A payload that actually sends a sampling key is caught even though the
        # guard comment (which quotes `temperature`) is present...
        regressed = (
            "// do not add a `temperature` field; "
            "models reject sampling parameters with a 400\n"
            "    body: JSON.stringify({ model: MODEL, max_tokens: 2048, "
            "temperature: 0.2, messages: [] });\n"
        )
        self.assertEqual(SAMPLING_KEY.findall(regressed), ["temperature"])
        # ...and the clean form (comment only, no key) is not a false positive.
        clean = (
            "// do not add a `temperature`, `top_p`, or `top_k` field; "
            "models reject sampling parameters with a 400\n"
            "    body: JSON.stringify({ model: MODEL, max_tokens: 2048, "
            "messages: [] });\n"
        )
        self.assertEqual(SAMPLING_KEY.findall(clean), [])


if __name__ == "__main__":
    unittest.main()
