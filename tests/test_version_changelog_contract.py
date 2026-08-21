"""Generator + curation contract for the version_changelog add-on.

Proves the add-on is off by default, stamps for every declared stack with no token
leaks, and — the part that matters — that the changelog generator refuses to publish
anything a human has not read. The heuristic that proposes entries is deliberately
fallible; these tests pin the gate that stands behind it.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addons" / "version_changelog" / "common"
GENERATOR = ROOT / "bin" / "generate.py"
CONFIG = json.loads((ROOT / "firestarter.config.json").read_text())
GEN = ADDON / "scripts" / "changelog-gen.py"

LEAK = re.compile(r"\{\{")


def _stamp(output: Path, stack: str, *, enable: bool) -> None:
    args = [
        sys.executable, str(GENERATOR), "--defaults",
        "--set", f"stack={stack}",
        "--output", str(output),
    ]
    if enable:
        args += ["--set", "include_version_changelog=yes"]
    subprocess.run(args, check=True, capture_output=True, text=True)


class GeneratorContract(unittest.TestCase):
    def test_registered_and_off_by_default(self):
        choices = CONFIG["include_version_changelog"]
        self.assertEqual(choices[0], "no", "add-on must be opt-in")
        self.assertIn("yes", choices)

    def test_absent_unless_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "proj"
            _stamp(out, CONFIG["stack"][0], enable=False)
            self.assertFalse(list(out.rglob("version-changelog.js")))
            self.assertFalse(list(out.rglob("VERSION_CHANGELOG.md")))

    def test_stamps_for_every_stack_without_leaks(self):
        for stack in CONFIG["stack"]:
            with self.subTest(stack=stack), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "proj"
                _stamp(out, stack, enable=True)
                for name in ("version-changelog.js", "VERSION_CHANGELOG.md", "changelog-gen.py"):
                    hits = list(out.rglob(name))
                    self.assertTrue(hits, f"{name} missing for stack {stack}")
                    for hit in hits:
                        self.assertIsNone(LEAK.search(hit.read_text()),
                                          f"unsubstituted token in {hit}")


class CurationGate(unittest.TestCase):
    """The generator must fail closed. These are the rules that keep an internal
    sentence out of a customer-facing changelog."""

    def _publish(self, draft: dict, tmp: Path, rollback: dict | None = None):
        dpath = tmp / "draft.json"
        dpath.write_text(json.dumps(draft))
        args = [sys.executable, str(GEN), "publish",
                "--draft", str(dpath), "--out", str(tmp / "out.json")]
        if rollback is not None:
            rpath = tmp / "rollback.json"
            rpath.write_text(json.dumps(rollback))
            args += ["--rollback-map", str(rpath)]
        return subprocess.run(args, capture_output=True, text=True)

    def test_unreviewed_release_is_never_published(self):
        draft = {"releases": [{"id": "v1", "reviewed": False,
                               "notes": [{"include": True, "text": "Something"}]}]}
        with tempfile.TemporaryDirectory() as tmp:
            res = self._publish(draft, Path(tmp))
        self.assertNotEqual(res.returncode, 0, "unreviewed release must not publish")
        self.assertIn("reviewed", res.stderr)

    def test_excluded_notes_do_not_reach_output(self):
        draft = {"releases": [{
            "id": "v1", "reviewed": True,
            "notes": [
                {"include": True, "text": "Faster export"},
                {"include": False, "text": "Audio drifted from its beat", "_commit": "abc123"},
            ],
        }]}
        with tempfile.TemporaryDirectory() as tmp:
            res = self._publish(draft, Path(tmp))
            self.assertEqual(res.returncode, 0, res.stderr)
            out = json.loads((Path(tmp) / "out.json").read_text())
        highlights = out["releases"][0]["highlights"]
        self.assertEqual(highlights, ["Faster export"])
        blob = json.dumps(out)
        self.assertNotIn("drifted", blob)
        self.assertNotIn("abc123", blob, "commit hashes are internal")

    def test_rollback_disabled_unless_url_supplied(self):
        draft = {"releases": [
            {"id": "v2", "reviewed": True, "notes": [{"include": True, "text": "New"}]},
            {"id": "v1", "reviewed": True, "notes": [{"include": True, "text": "Old"}]},
        ]}
        rollback = {"_default_reason": "Predates the archive.",
                    "v1": {"url": "https://example.com/deploy/v1/"}}
        with tempfile.TemporaryDirectory() as tmp:
            res = self._publish(draft, Path(tmp), rollback)
            self.assertEqual(res.returncode, 0, res.stderr)
            out = json.loads((Path(tmp) / "out.json").read_text())
        by_id = {r["id"]: r for r in out["releases"]}
        self.assertFalse(by_id["v2"]["rollback"]["available"])
        self.assertTrue(by_id["v2"]["rollback"]["reason"], "a disabled entry must explain itself")
        self.assertTrue(by_id["v1"]["rollback"]["available"])
        self.assertEqual(by_id["v1"]["rollback"]["url"], "https://example.com/deploy/v1/")
        # the map's own private key must not surface as a release
        self.assertNotIn("_default_reason", by_id)


class Placement(unittest.TestCase):
    """A pinned stamp must open its panel away from the edge it is pinned to, or the
    panel runs off-screen — the failure mode you only notice on someone else's laptop."""

    def setUp(self):
        self.src = (ADDON / "assets" / "version-changelog.js").read_text()

    def test_all_modes_present(self):
        for mode in ("float", "header", "footer", "side"):
            self.assertIn(f'placement="{mode}"', self.src, f"{mode} placement missing")

    def test_pinned_modes_position_themselves(self):
        self.assertRegex(self.src, r':host\(\[placement="float"\]\)[^{]*,?[\s\S]{0,200}?position:\s*fixed')

    def test_panel_opens_away_from_the_pinned_edge(self):
        # top-pinned opens downward
        self.assertIn(':host([placement="header"]) .panel { bottom: auto; top:', self.src)
        # right-pinned aligns right so it cannot overflow the viewport
        self.assertIn("left: auto; right: 0;", self.src)
        # side opens leftward
        self.assertIn(':host([placement="side"]) .panel { right: calc(100% + .5rem)', self.src)

    def test_placement_is_observed_at_runtime(self):
        self.assertIn('"placement"', self.src)
        self.assertIn('"corner"', self.src)


class ComponentSurface(unittest.TestCase):
    def test_escapes_and_never_mutates(self):
        src = (ADDON / "assets" / "version-changelog.js").read_text()
        self.assertIn("escapeHtml", src)
        self.assertIn("cancelable: true", src)
        # rendering paths must go through the escaper, so a note cannot inject markup
        self.assertNotRegex(src, r"innerHTML\s*=\s*`?\$\{(?!head)[a-z]", )
        for prop in ("--changelog-ink", "--changelog-surface", "--changelog-accent"):
            self.assertIn(prop, src, f"{prop} must be themeable by the host")


if __name__ == "__main__":
    unittest.main()
