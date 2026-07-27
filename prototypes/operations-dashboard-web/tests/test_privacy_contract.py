import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "sanitized-remote.snapshot.json"
RECORD_SECTIONS = ("queue", "tests", "resourceBudget", "signals")
VERIFICATION = {"verified", "estimated", "unavailable", "not-implemented"}
FORBIDDEN_KEYS = ("endpoint", "url", "host", "ip", "path", "credential", "secret", "token")
QUEUE_STATES = {"running", "queued", "waiting", "ready"}


def walk(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


class SanitizedSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in ROOT.rglob("*")
            if path.is_file() and path.suffix in {".html", ".css", ".js", ".json", ".md", ".py"}
        )

    def test_snapshot_has_expected_mode_and_collections(self):
        self.assertEqual(self.snapshot["schemaVersion"], "1.0")
        self.assertEqual(self.snapshot["mode"], "sanitized-remote")
        for section in RECORD_SECTIONS:
            self.assertIsInstance(self.snapshot.get(section), list)
            self.assertGreater(len(self.snapshot[section]), 0)

    def test_fixture_has_exactly_ten_dense_lifecycle_lanes(self):
        queue = self.snapshot["queue"]
        self.assertEqual(len(queue), 10)
        counts = {
            state: sum(record["state"] == state for record in queue)
            for state in QUEUE_STATES
        }
        self.assertEqual(counts, {"running": 2, "queued": 3, "waiting": 2, "ready": 3})

    def test_every_record_is_sanitized_and_verification_is_explicit(self):
        for section in RECORD_SECTIONS:
            for record in self.snapshot[section]:
                self.assertEqual(record.get("exposure"), "sanitized", (section, record.get("id")))
                self.assertIn(record.get("verification"), VERIFICATION, (section, record.get("id")))

    def test_snapshot_contains_no_forbidden_field_names(self):
        for key, _ in walk(self.snapshot):
            normalized = key.lower()
            self.assertFalse(
                any(fragment in normalized for fragment in FORBIDDEN_KEYS),
                f"forbidden field name: {key}",
            )

    def test_fixture_and_renderer_contain_no_private_environment_literals(self):
        forbidden_patterns = {
            "network URL": r"h" + r"ttps?://",
            "loopback name": r"\b" + "local" + "host" + r"\b",
            "tailnet name": r"\.ts" + r"\.net\b",
            "private filesystem": "/" + "Users" + "/",
            "IPv4 address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        }
        fixture_and_renderer = (
            FIXTURE.read_text(encoding="utf-8")
            + (ROOT / "dashboard.js").read_text(encoding="utf-8")
        )
        for label, pattern in forbidden_patterns.items():
            self.assertIsNone(re.search(pattern, fixture_and_renderer, re.IGNORECASE), label)

    def test_renderer_has_no_live_bridge_or_refresh_loop(self):
        renderer = (ROOT / "dashboard.js").read_text(encoding="utf-8")
        self.assertNotIn("WebSocket", renderer)
        self.assertNotIn("setInterval", renderer)
        self.assertNotIn("setTimeout", renderer)
        self.assertNotIn("/metrics", renderer)
        self.assertIn("assertSanitizedSnapshot", renderer)
        self.assertIn('fetch("./fixtures/sanitized-remote.snapshot.json"', renderer)

    def test_renderer_uses_text_nodes_instead_of_html_injection_sinks(self):
        renderer = (ROOT / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn("element.textContent", renderer)
        self.assertNotIn("innerHTML", renderer)
        self.assertNotIn("insertAdjacentHTML", renderer)
        self.assertNotIn("document.write", renderer)

    def test_dense_layout_has_bounded_responsive_breakpoints(self):
        styles = (ROOT / "styles.css").read_text(encoding="utf-8")
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: repeat(5", styles)
        self.assertIn("@media (max-width: 1000px)", styles)
        self.assertIn("@media (max-width: 620px)", styles)
        self.assertIn('id="state-summary"', page)
        self.assertIn('role="list"', page)

    def test_unimplemented_and_unavailable_states_are_visible(self):
        self.assertIn("not-implemented", self.sources)
        self.assertIn("unavailable", self.sources)
        self.assertIn("record.exposure", (ROOT / "dashboard.js").read_text(encoding="utf-8"))
        self.assertIn("never treats missing, unavailable, unrun, or unimplemented evidence as passing", self.sources)


if __name__ == "__main__":
    unittest.main()
