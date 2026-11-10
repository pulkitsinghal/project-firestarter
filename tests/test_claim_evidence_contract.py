"""Synthetic incident regressions; no private incident content is published."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "template/scripts/claim-evidence.py"
spec = importlib.util.spec_from_file_location("claim_evidence", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def source(scope="main", **updates):
    value = dict(id=scope, scope=scope, source_class="primary", reference="fixture:source",
                 observed_at=1000, result="supports", coverage_complete=True, state=None)
    return dict(value, **updates)


def request(kind="observation", scopes=None, evidence=None):
    return dict(kind=kind, now=1000, max_age_seconds=60,
                required_scopes=scopes or ["main"],
                evidence=[source()] if evidence is None else evidence)


class ClaimEvidenceContract(unittest.TestCase):
    def assert_code(self, payload, code):
        result = guard.validate(payload)
        self.assertNotEqual(result["decision"], "allow")
        self.assertIn(code, result["codes"])

    def test_primary_observation(self):
        self.assertEqual(guard.validate(request()), {"decision": "allow", "codes": []})

    def test_database_only_from_main_repo_ignores_private_fixture(self):
        payload = request("absence", ["main", "private-fixtures"],
                          [source(result="not_found")])
        self.assert_code(payload, "INCOMPLETE_COVERAGE")
        payload["evidence"].append(source("private-fixtures"))
        self.assert_code(payload, "POSITIVE_FINDING_PREVENTS_ABSENCE")

    def test_scoped_complete_absence(self):
        self.assertEqual(guard.validate(request("absence", evidence=[source(result="not_found")]))["decision"], "allow")

    def test_invented_question_cannot_claim_source_provenance(self):
        self.assert_code(request("provenance", evidence=[source(source_class="synthetic")]),
                         "SYNTHETIC_NOT_PROVENANCE")

    def test_inferred_or_reported_is_not_primary(self):
        for classification in ("reported", "inferred"):
            self.assert_code(request("provenance", evidence=[source(source_class=classification)]), "NO_PRIMARY_SUPPORT")

    def test_idle_or_scheduled_worker_is_not_active(self):
        for state in ("idle", "scheduled", None):
            self.assert_code(request("worker_active", evidence=[source(state=state)]), "NO_ACTIVE_WORKER_RECEIPT")
        self.assertEqual(guard.validate(request("worker_active", evidence=[source(state="active")]))["decision"], "allow")

    def test_overnight_stale_worker(self):
        self.assert_code(request("worker_active", evidence=[source(state="active", observed_at=0)]), "STALE_EVIDENCE")

    def test_calendar_family_block_is_not_appointment_confirmation(self):
        self.assert_code(request("appointment", ["calendar"], [source("calendar")]), "APPOINTMENT_SOURCES_MISSING")
        payload = request("appointment", ["calendar", "messages"], [source("calendar"), source("messages")])
        self.assert_code(payload, "NO_APPOINTMENT_CONFIRMATION")
        payload["evidence"][1]["state"] = "confirmed"
        self.assertEqual(guard.validate(payload)["decision"], "allow")
        payload["evidence"][0]["state"] = "cancelled"
        self.assert_code(payload, "APPOINTMENT_CANCELLED")

    def test_conflicting_source_is_not_silently_dropped(self):
        self.assert_code(request(evidence=[source(), source(id="second", result="contradicts")]), "CONFLICTING_EVIDENCE")

    def test_missing_stale_future_unavailable_and_partial_sources(self):
        cases = [([], "INCOMPLETE_COVERAGE"),
                 ([source(observed_at=939)], "STALE_EVIDENCE"),
                 ([source(observed_at=1001)], "FUTURE_EVIDENCE"),
                 ([source(result="unavailable")], "INCOMPLETE_COVERAGE"),
                 ([source(coverage_complete=False)], "INCOMPLETE_COVERAGE")]
        for evidence, code in cases:
            self.assert_code(request(evidence=evidence), code)

    def test_invalid_types_fail_closed(self):
        for field, value in [("kind", []), ("now", True), ("now", float("nan")),
                             ("max_age_seconds", 0), ("max_age_seconds", 86401),
                             ("required_scopes", []), ("required_scopes", ["main", "main"]),
                             ("evidence", [source(), source()])]:
            payload = request()
            payload[field] = value
            self.assert_code(payload, "INVALID_INPUT")
        for field, value in [("source_class", []), ("result", {}), ("observed_at", True),
                             ("coverage_complete", "true"), ("reference", " "), ("state", [])]:
            self.assert_code(request(evidence=[source(**{field: value})]), "INVALID_INPUT")

    def test_no_source_content_echoed_and_cli_exit_codes(self):
        for payload, expected in [(request(), 0), (request(evidence=[]), 1), ({}, 2)]:
            run = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload),
                                 text=True, capture_output=True)
            self.assertEqual(run.returncode, expected)
            self.assertNotIn("fixture:source", run.stdout + run.stderr)
        for malformed in ['{"kind":1,"kind":2}', 'not json']:
            run = subprocess.run([sys.executable, str(SCRIPT)], input=malformed, text=True, capture_output=True)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(json.loads(run.stdout)["codes"], ["INVALID_INPUT"])

    def test_stamped_tool_and_instruction_present(self):
        self.assertIn("template/docs/CLAIM_EVIDENCE.md", (ROOT / "AGENTS.md").read_text())
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "generated"
            subprocess.run([sys.executable, str(ROOT / "bin/generate.py"), "--values",
                            str(ROOT / "examples/fastapi-next.answers.json"), "--output", str(output)],
                           check=True, capture_output=True)
            self.assertEqual((output / "scripts/claim-evidence.py").read_bytes(), SCRIPT.read_bytes())
            self.assertIn("CLAIM_EVIDENCE.md", (output / "AGENTS.md").read_text())
            self.assertTrue((output / "docs/CLAIM_EVIDENCE.md").exists())

    def test_active_receipt_cannot_mask_later_idle_or_unavailable(self):
        self.assert_code(request("worker_active", evidence=[
            source(id="old", observed_at=999, state="active"), source(state="idle")
        ]), "CONFLICTING_WORKER_STATE")
        self.assert_code(request("worker_active", evidence=[
            source(id="old", observed_at=999, state="active"),
            source(result="unavailable", coverage_complete=False)
        ]), "UNAVAILABLE_SOURCE")

    def test_huge_json_number_fails_without_traceback(self):
        payload = request()
        payload["now"] = 10 ** 400
        run = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload),
                             text=True, capture_output=True)
        self.assertEqual(run.returncode, 2)
        self.assertEqual(run.stderr, "")
        self.assertEqual(json.loads(run.stdout)["codes"], ["INVALID_INPUT"])

    def test_partial_or_unavailable_never_hidden_by_complete_observation(self):
        for kind in ("observation", "absence"):
            result = "not_found" if kind == "absence" else "supports"
            for change, code in [({"coverage_complete": False}, "PARTIAL_SOURCE"),
                                 ({"result": "unavailable"}, "UNAVAILABLE_SOURCE")]:
                self.assert_code(request(kind, evidence=[source(id="old", result=result),
                    source(**dict({"result": result}, **change))]), code)

    def test_all_conflicting_worker_states_are_blocked(self):
        for state in ("idle", "scheduled", "cancelled", "confirmed", None):
            result = guard.validate(request("worker_active", evidence=[
                source(id="old", state="active"), source(state=state)]))
            self.assertEqual(result["decision"], "block")

    def test_all_oversized_numeric_fields_rejected(self):
        for field in ("now", "max_age_seconds", "observed_at"):
            payload = request()
            target = payload["evidence"][0] if field == "observed_at" else payload
            target[field] = 10 ** 400
            self.assert_code(payload, "INVALID_INPUT")
            run = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload),
                                 text=True, capture_output=True)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(run.stderr, "")

    def test_idle_state_cannot_hide_behind_not_found_result(self):
        result = guard.validate(request("worker_active", evidence=[
            source(id="prior", state="active", observed_at=999),
            source(state="idle", result="not_found")]))
        self.assertEqual(result["decision"], "block")
        self.assertIn("CONFLICTING_WORKER_STATE", result["codes"])
