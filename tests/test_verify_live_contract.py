"""Adversarial contract for deployed-artifact verification."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "template" / "scripts" / "verify-live.sh"


class LiveHandler(BaseHTTPRequestHandler):
    counts: dict[str, int] = {}

    def log_message(self, *_args: object) -> None:
        return

    def _common_request_contract(self) -> bool:
        if not self.headers.get("User-Agent", "").startswith("Mozilla/5.0"):
            self.send_error(400, "browser user-agent required")
            return False
        if self.headers.get("Cache-Control") != "no-cache":
            self.send_error(400, "cache bypass required")
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._common_request_contract():
            return
        path = self.path.split("?", 1)[0]
        LiveHandler.counts[path] = LiveHandler.counts.get(path, 0) + 1

        if path.endswith("/media.mp4"):
            if self.headers.get("Range") == "bytes=1-2" and not path.startswith("/no-range"):
                self.send_response(206)
                self.send_header("Content-Range", "bytes 1-2/100")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"xx")
            else:
                self.send_response(200)
                self.send_header("Content-Length", "100")
                self.end_headers()
                self.wfile.write(b"x" * 100)
            return

        if path.startswith("/redirect/"):
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
            return

        if path.startswith("/never/"):
            build, note = "stale", "wanted"
        elif path.startswith("/eventual/") and LiveHandler.counts[path] == 1:
            build, note = "stale", ""
        else:
            build, note = "wanted", ""
        body = json.dumps({"git_sha": build, "note": note}).encode()
        self.send_response(200)
        content_type = "text/html" if path.startswith("/wrong-type/") else "application/json"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class VerifyLiveContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        LiveHandler.counts = {}
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), LiveHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT), "--interval", "0", "--timeout", "2", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_waits_for_every_hostname_then_checks_range(self) -> None:
        result = self.run_script(
            "--attempts", "3", "--expect", "wanted", "--range", "/media.mp4",
            f"{self.base}/eventual", f"{self.base}/ready",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("honors byte ranges"), 2)
        self.assertIn("across 2 hostname(s)", result.stdout)

    def test_expected_text_elsewhere_cannot_fake_the_provenance_field(self) -> None:
        result = self.run_script(
            "--attempts", "2", "--expect", "wanted", f"{self.base}/never"
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("did not converge", result.stderr)
        self.assertNotIn('{"git_sha"', result.stderr, "response bodies must not leak to logs")

    def test_redirect_or_missing_range_support_fails_closed(self) -> None:
        redirected = self.run_script(
            "--attempts", "1", "--expect", "wanted", f"{self.base}/redirect"
        )
        self.assertEqual(redirected.returncode, 1)
        self.assertIn("HTTP 302", redirected.stderr)

        no_range = self.run_script(
            "--attempts", "1", "--expect", "wanted",
            "--range", f"{self.base}/no-range/media.mp4", f"{self.base}/ready",
        )
        self.assertEqual(no_range.returncode, 1)
        self.assertIn("range probe failed", no_range.stderr)

    def test_html_interstitial_and_unlisted_paths_do_not_leak(self) -> None:
        wrong_type = self.run_script(
            "--attempts", "1", "--expect", "wanted", f"{self.base}/wrong-type"
        )
        self.assertEqual(wrong_type.returncode, 1)
        self.assertIn("was not JSON", wrong_type.stderr)

        sensitive_path = "unguessable-review-path"
        success = self.run_script(
            "--attempts", "1", "--expect", "wanted", f"{self.base}/{sensitive_path}"
        )
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertNotIn(sensitive_path, success.stdout + success.stderr)

    def test_absolute_probe_path_and_credential_bearing_base_are_refused(self) -> None:
        absolute = self.run_script(
            "--attempts", "1", "--expect", "wanted",
            "--path", f"{self.base}/ready/health", f"{self.base}/never",
        )
        self.assertEqual(absolute.returncode, 2)
        self.assertIn("relative to each BASE_URL", absolute.stderr)

        credentials = self.run_script(
            "--attempts", "1", "--expect", "wanted", "https://user:secret@example.test"
        )
        self.assertEqual(credentials.returncode, 2)
        self.assertIn("credentials in BASE_URL are forbidden", credentials.stderr)
        self.assertNotIn("user:secret", credentials.stderr)

    def test_every_stack_stamps_the_script_and_safe_make_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            for answers in sorted((ROOT / "examples").glob("*.answers.json")):
                with self.subTest(answers=answers.name):
                    output = Path(temp) / answers.stem
                    subprocess.run(
                        ["python3", str(ROOT / "bin" / "generate.py"), "--values",
                         str(answers), "--output", str(output)],
                        cwd=ROOT, check=True, capture_output=True, text=True,
                    )
                    stamped = output / "scripts" / "verify-live.sh"
                    self.assertTrue(stamped.exists())
                    self.assertNotIn("{{", stamped.read_text())
                    makefile = (output / "Makefile").read_text()
                    self.assertIn("verify-live:", makefile)
                    self.assertIn('test -n "$(BASE)"', makefile)
                    self.assertIn('test -n "$(EXPECT)"', makefile)
                    self.assertIn('set -- "$$@" --field "$(LIVE_FIELD)"', makefile)

    def test_docs_and_artifacts_exclude_source_specific_material(self) -> None:
        files = [
            SCRIPT, ROOT / "template" / "docs" / "DEPLOY_POLICY.md",
            *(ROOT / "stacks").glob("*/Makefile"),
        ]
        text = "\n".join(path.read_text() for path in files).lower()
        for forbidden in (
            "auggiehealth", "west nile", "share-desk", "research-access",
            "cloudflare_account_id", "cf-access-client-secret", "@example.com",
        ):
            self.assertNotIn(forbidden, text)

        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("tests.test_verify_live_contract", workflow)


if __name__ == "__main__":
    unittest.main()
