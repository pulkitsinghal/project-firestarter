"""Generator + behaviour contract for the datastore_advisor add-on.

Proves the add-on is off by default, stamps for every declared stack with tokens
substituted (no leaks), that the *stamped* tool passes its offline self-test, and
that the properties which make it an advisor rather than a quiz actually hold:
the default stays boring, a sparse single-hop "graph" is disqualified with its
own numbers quoted back, every catalog entry declares what it is wrong for, and
the edition check and restore drill are emitted unconditionally.
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
ADDON = ROOT / "addons" / "datastore_advisor" / "common"
TOOL = ADDON / "tools" / "datastore_advisor"
GENERATOR = ROOT / "bin" / "generate.py"
CONFIG = json.loads((ROOT / "firestarter.config.json").read_text())

# The only legitimate "{{" in generated output is a GitHub expression or JSX;
# neither appears in this add-on's files, so any "{{" here is a real leak.
LEAK = re.compile(r"\{\{")

CATALOG = json.loads((TOOL / "catalog.json").read_text())
QUESTIONS = json.loads((TOOL / "questions.json").read_text())


def _stamp(output: Path, stack: str, *, enable: bool) -> None:
    args = [
        sys.executable, str(GENERATOR), "--defaults",
        "--set", f"stack={stack}",
        "--output", str(output),
    ]
    if enable:
        args += ["--set", "include_datastore_advisor=yes"]
    subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True)


def _advise(project: Path, answers: dict) -> dict:
    """Run the *stamped* CLI and return its JSON recommendation."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(answers, fh)
        answers_path = fh.name
    result = subprocess.run(
        [sys.executable, "-B", "-m", "tools.datastore_advisor.cli",
         "--answers", answers_path, "--json"],
        cwd=project, check=False, capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)


class DatastoreAdvisorContractTests(unittest.TestCase):
    def test_registered_as_closed_choice_and_off_by_default(self) -> None:
        self.assertEqual(CONFIG["include_datastore_advisor"], ["no", "yes"])
        self.assertIn('"datastore_advisor"', GENERATOR.read_text())

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "default"
            _stamp(output, "fastapi-next", enable=False)
            self.assertFalse((output / "tools" / "datastore_advisor").exists())
            self.assertFalse((output / "docs" / "DATASTORE_ADVISOR.md").exists())

    def test_every_stack_stamps_clean_and_selftest_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for stack in CONFIG["stack"]:
                with self.subTest(stack=stack):
                    output = root / stack
                    _stamp(output, stack, enable=True)

                    for rel in (
                        "tools/datastore_advisor/advisor.py",
                        "tools/datastore_advisor/cli.py",
                        "tools/datastore_advisor/catalog.json",
                        "tools/datastore_advisor/questions.json",
                        "tools/datastore_advisor/selftest.py",
                        "docs/DATASTORE_ADVISOR.md",
                        "docs/DATASTORE_DECISION.md",
                    ):
                        self.assertTrue((output / rel).is_file(), rel)

                    # No unsubstituted tokens anywhere in the stamped add-on tree.
                    targets = list((output / "tools" / "datastore_advisor").rglob("*"))
                    targets += [output / "docs" / "DATASTORE_ADVISOR.md",
                                output / "docs" / "DATASTORE_DECISION.md"]
                    for path in targets:
                        if path.is_file():
                            self.assertIsNone(
                                LEAK.search(path.read_text(encoding="utf-8", errors="ignore")),
                                f"token leak in {path}",
                            )

                    # Tokens really substituted.
                    guide = (output / "docs" / "DATASTORE_ADVISOR.md").read_text()
                    self.assertIn("Project Acme", guide)
                    self.assertIn("acme", guide)

                    # The stamped Python passes its offline self-test.
                    result = subprocess.run(
                        [sys.executable, "-B", "tools/datastore_advisor/selftest.py"],
                        cwd=output, check=False, capture_output=True, text=True, timeout=90,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("all checks passed", result.stdout)

    def test_stamped_tool_defaults_to_boring(self) -> None:
        """The most common right answer should be the one it actually gives."""
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "p"
            _stamp(project, "fastapi-next", enable=True)
            rec = _advise(project, {
                "hold_data": "must_hold",
                "workload_shape": ["relational"],
                "scale": "hundreds_of_thousands",
                "traffic_profile": "steady",
                "isolation_model": "row_level",
                "isolation_is_the_reason": "no",
                "regulated": ["none"],
                "team": "small_team",
                "backup_restore": "restored",
                "exit_tolerance": "prefer",
            })
            self.assertEqual(rec["primary"], "postgres")
            # It argues against its own answer, always.
            self.assertGreaterEqual(len(rec["case_against"]), 3)
            self.assertGreaterEqual(len(rec["what_would_change_this"]), 2)

    def test_stamped_tool_disqualifies_a_sparse_graph_with_its_own_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "p"
            _stamp(project, "fastapi-next", enable=True)
            rec = _advise(project, {
                "hold_data": "must_hold",
                "workload_shape": ["graph"],
                "graph_edge_density": "under_1",
                "graph_traversal_depth": "one_hop",
                "graph_algorithms": "none",
                "scale": "thousands",
                "traffic_profile": "mostly_idle",
                "isolation_model": "row_level",
                "isolation_is_the_reason": "yes",
                "regulated": ["none"],
                "team": "solo",
                "backup_restore": "none",
                "exit_tolerance": "prefer",
            })
            self.assertEqual(rec["primary"], "postgres")
            ruled_out = {d["engine"]: d["reason"] for d in rec["disqualified"]}
            self.assertIn("graph_db", ruled_out)
            self.assertIn("edge density", ruled_out["graph_db"])
            self.assertIn("algorithms", ruled_out["graph_db"])

            # Choosing for an isolation property escalates the edition check.
            edition = [v for v in rec["verifications"] if v["id"] == "edition_feature_check"]
            self.assertEqual(len(edition), 1)
            self.assertTrue(edition[0]["blocking"])
            self.assertFalse(rec["operationally_ready"])

    def test_unconditional_verifications_are_unconditional(self) -> None:
        """The edition check and the restore drill are the point of the tool."""
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "p"
            _stamp(project, "chrome-extension", enable=True)
            rec = _advise(project, {"hold_data": "unknown", "team": "solo",
                                    "backup_restore": "restored"})
            ids = {v["id"] for v in rec["verifications"]}
            self.assertIn("edition_feature_check", ids)
            self.assertIn("restore_drill", ids)

    def test_catalog_states_what_each_engine_is_wrong_for(self) -> None:
        """A catalog of pitches would be worse than no catalog."""
        required = {
            "postgres", "postgres_pgvector", "sqlite", "neon", "supabase",
            "cloud_sql", "dynamodb", "firestore", "redis_valkey", "graph_db",
            "device_local",
        }
        ids = {e["id"] for e in CATALOG["engines"]}
        self.assertTrue(required.issubset(ids), required - ids)
        for eng in CATALOG["engines"]:
            with self.subTest(engine=eng["id"]):
                self.assertTrue(eng.get("wrong_for"), "no wrong_for")
                self.assertTrue(eng.get("exit_cost"), "no exit_cost")
                for cite in eng.get("citations") or []:
                    self.assertTrue(cite.get("url", "").startswith("http"))
                    self.assertTrue(cite.get("accessed"))
                    self.assertTrue(cite.get("claim"))

    def test_holding_the_data_is_asked_first(self) -> None:
        axes = sorted(QUESTIONS["axes"], key=lambda a: a["order"])
        self.assertEqual(axes[0]["id"], "hold_data")
        self.assertTrue(all(a.get("why_it_matters") for a in QUESTIONS["axes"]))

    def test_tool_has_no_heavy_deps(self) -> None:
        for name in ("advisor.py", "cli.py", "selftest.py"):
            src = (TOOL / name).read_text()
            for banned in ("import requests", "import httpx", "import yaml",
                           "import aiohttp", "import pydantic"):
                self.assertNotIn(banned, src, f"{name} must stay stdlib-only")


if __name__ == "__main__":
    unittest.main()
