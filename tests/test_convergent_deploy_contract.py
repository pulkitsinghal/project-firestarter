"""Property contract for the convergent_deploy add-on.

Each test is a collision that actually happened while shipping a share to an outside
collaborator on 20-21 Aug 2026. They are the reason the module exists, so they are
written as properties rather than as unit tests of the implementation: what must hold
is that two agents deploying concurrently cannot lose each other's work, and that an
agent which loses a race finds out.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addons" / "convergent_deploy" / "common"
CONFIG = json.loads((ROOT / "firestarter.config.json").read_text())

_spec = importlib.util.spec_from_file_location("converge", ADDON / "scripts" / "converge.py")
converge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(converge)


class Registration(unittest.TestCase):
    def test_registered_and_off_by_default(self):
        choices = CONFIG["include_convergent_deploy"]
        self.assertEqual(choices[0], "no", "add-on must be opt-in")
        self.assertIn("yes", choices)

    def test_wired_into_the_generator(self):
        self.assertIn('"convergent_deploy"', (ROOT / "bin" / "generate.py").read_text(),
                      "an addon absent from generate.py's list is never stamped")


class Commutative(unittest.TestCase):
    """Two agents publishing different artefacts must converge to the same state
    whichever one deploys last. That is what removes the need for them to take turns."""

    A = {"id": "aaa", "title": "mine", "added": "2026-08-20T10:00:00+00:00"}
    B = {"id": "bbb", "title": "theirs", "added": "2026-08-20T11:00:00+00:00"}

    def test_neither_agent_loses_its_artefact(self):
        m1, _ = converge.merge_manifests({"entries": [self.A]}, {"entries": [self.B]})
        m2, _ = converge.merge_manifests({"entries": [self.B]}, {"entries": [self.A]})
        self.assertEqual({e["id"] for e in m1["entries"]}, {"aaa", "bbb"})
        self.assertEqual(m1, m2, "merge must not depend on deploy order")

    def test_adopted_ids_are_reported(self):
        _, adopted = converge.merge_manifests({"entries": [self.A]}, {"entries": [self.B]})
        self.assertEqual(adopted, ["bbb"])

    def test_newer_edit_wins_without_dropping_unrelated_entries(self):
        older = {"id": "aaa", "title": "old", "added": "2026-08-20T09:00:00+00:00"}
        newer = {"id": "aaa", "title": "new", "added": "2026-08-20T12:00:00+00:00"}
        merged, _ = converge.merge_manifests({"entries": [newer]},
                                             {"entries": [older, self.B]})
        by = {e["id"]: e for e in merged["entries"]}
        self.assertEqual(by["aaa"]["title"], "new")
        self.assertIn("bbb", by, "an unrelated artefact must survive an update to another")

    def test_empty_remote_is_normal(self):
        merged, adopted = converge.merge_manifests({"entries": [self.A]}, None)
        self.assertEqual([e["id"] for e in merged["entries"]], ["aaa"])
        self.assertEqual(adopted, [])


class Fencing(unittest.TestCase):
    """The live site is the register. A deploy publishes one past what it read."""

    def setUp(self):
        self._orig = converge._fetch_json
        self.addCleanup(lambda: setattr(converge, "_fetch_json", self._orig))

    def test_token_advances_past_the_live_value(self):
        converge._fetch_json = lambda base, name: {"token": 7}
        self.assertEqual(converge.next_token("https://example.invalid"), 8)

    def test_token_starts_at_one_when_nothing_is_published(self):
        converge._fetch_json = lambda base, name: None
        self.assertEqual(converge.next_token("https://example.invalid"), 1)

    def test_a_lost_race_is_detected_not_assumed_away(self):
        converge._fetch_json = lambda base, name: {"token": 9}
        msg = converge.verify_not_superseded("https://example.invalid", 8)
        self.assertIsNotNone(msg, "a deploy that lost the race must say so")

    def test_our_own_token_landing_is_silence(self):
        converge._fetch_json = lambda base, name: {"token": 8}
        self.assertIsNone(converge.verify_not_superseded("https://example.invalid", 8))


class Additive(unittest.TestCase):
    """An artefact we do not hold locally must survive our deploy."""

    def setUp(self):
        self._orig = converge._fetch_file
        self.addCleanup(lambda: setattr(converge, "_fetch_file", self._orig))

    def test_live_site_beats_a_stale_local_backup(self):
        """The regression a fresh clone actually hit on 21 Aug 2026.

        Backups are often committed, so a clone carries whatever was backed up whenever
        it was committed — in the real case a 47 KB page from before the media moved to
        a range-serving host, against a 105 KB live page. Preferring the cheap local
        copy would have republished the old build over the working one. Cheapness is the
        wrong ordering criterion; currency is the right one.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bak = root / ".backups" / "bak-old-bbb"
            bak.mkdir(parents=True)
            (bak / "index.html").write_text("STALE BUILD")
            live = root / "deploy"
            live.mkdir()

            def fake(url, dest):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text("CURRENT BUILD")
                return True

            converge._fetch_file = fake
            healed, unhealable = converge.heal(
                live, {"entries": [{"id": "bbb", "files": ["index.html"]}]},
                "https://example.test", root / ".backups")
            self.assertEqual(unhealable, [])
            self.assertEqual((live / "bbb" / "index.html").read_text(), "CURRENT BUILD")
            self.assertIn("from live site", healed[0])

    def test_backup_is_the_fallback_and_announces_itself_as_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bak = root / ".backups" / "bak-old-bbb"
            bak.mkdir(parents=True)
            (bak / "index.html").write_text("<h1>theirs</h1>")
            live = root / "deploy"
            live.mkdir()
            converge._fetch_file = lambda url, dest: False      # live unreachable
            healed, unhealable = converge.heal(
                live, {"entries": [{"id": "bbb", "files": ["index.html"]}]},
                "https://example.invalid", root / ".backups")
            self.assertEqual(unhealable, [])
            self.assertTrue((live / "bbb" / "index.html").exists())
            self.assertIn("STALE", healed[0],
                          "a backup restore must announce it may be an older build")

    def test_an_unrestorable_entry_is_named_never_silently_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = root / "deploy"
            live.mkdir()
            healed, unhealable = converge.heal(live, {"entries": [{"id": "ccc"}]},
                                               "https://example.invalid", root / ".backups")
            self.assertEqual(healed, [])
            self.assertTrue(unhealable and "ccc" in unhealable[0])

    def test_file_list_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "entry"
            (d / "data").mkdir(parents=True)
            (d / "index.html").write_text("x")
            (d / "data" / "a.csv").write_text("y")
            self.assertEqual(converge.file_list(d), ["data/a.csv", "index.html"])


if __name__ == "__main__":
    unittest.main()
