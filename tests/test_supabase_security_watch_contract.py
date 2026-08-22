"""Contract for the hosted Supabase Security Advisor watcher."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STACK = ROOT / "stacks" / "supabase-flutter"
SCRIPT = STACK / ".github" / "scripts" / "supabase-security-watch.mjs"
WORKFLOW = STACK / ".github" / "workflows" / "supabase-security-watch.yml"
DOC = STACK / "docs" / "SUPABASE_SECURITY_WATCH.md"

class SecurityWatchContract(unittest.TestCase):
    def classify(self, payload: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            source, result = Path(tmp) / "advisor.json", Path(tmp) / "result.json"
            source.write_text(payload)
            subprocess.run(["node", SCRIPT, source, result], check=True)
            return result.read_text()

    def test_clean_actionable_and_malformed_are_distinct(self):
        self.assertIn('"status": "clean"', self.classify('{"lints":[]}'))
        self.assertIn('"status": "action_required"', self.classify(
            '{"lints":[{"level":"ERROR","cache_key":"new","title":"Fix me"}]}'))
        self.assertIn('"status": "unhealthy"', self.classify("not-json"))
        self.assertIn('"status": "unhealthy"', self.classify(
            '{"lints":[{"level":"ERROR","title":"missing cache key"}]}'))

    def test_workflow_is_inert_until_configured_then_fail_closed(self):
        text = WORKFLOW.read_text()
        for phrase in ("vars.SUPABASE_PROJECT_REF != ''", "SUPABASE_ACCESS_TOKEN secret is missing",
                       "Advisor classifier crashed", "core.setFailed",
                       "cancel-in-progress: false", "issues: write"):
            self.assertIn(phrase, text)

    def test_docs_preserve_channel_specific_proof_and_secrets(self):
        text = " ".join(DOC.read_text().split())
        self.assertIn("one channel succeeding does not prove another", text)
        self.assertIn("advisors_read", text)
        self.assertIn("experimental/deprecated", text)
        self.assertNotIn("txt.att.net", text)

if __name__ == "__main__":
    unittest.main()
