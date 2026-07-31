"""Generator + transport contract for the local_ollama add-on.

Proves the add-on is off by default, stamps for every declared stack with tokens
substituted (no leaks), and that the *stamped* client's request/response
handling passes its offline self-test with zero network.
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
ADDON = ROOT / "addons" / "local_ollama" / "common"
GENERATOR = ROOT / "bin" / "generate.py"
CONFIG = json.loads((ROOT / "firestarter.config.json").read_text())

# The only legitimate "{{" in generated output is a GitHub expression or JSX;
# neither appears in this add-on's files, so any "{{" here is a real leak.
LEAK = re.compile(r"\{\{")


def _stamp(output: Path, stack: str, *, enable: bool) -> None:
    args = [
        sys.executable, str(GENERATOR), "--defaults",
        "--set", f"stack={stack}",
        "--output", str(output),
    ]
    if enable:
        args += ["--set", "include_local_ollama=yes"]
    subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True)


class LocalOllamaContractTests(unittest.TestCase):
    def test_registered_as_closed_choice_and_off_by_default(self) -> None:
        self.assertEqual(CONFIG["include_local_ollama"], ["no", "yes"])
        self.assertIn('"local_ollama"', GENERATOR.read_text())
        # tokens declared
        for token in ("ollama_host", "ollama_port", "ollama_model", "ollama_embed_model"):
            self.assertIn(token, CONFIG)

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "default"
            _stamp(output, "fastapi-next", enable=False)
            self.assertFalse((output / "local-ollama").exists())

    def test_every_stack_stamps_clean_and_selftest_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for stack in CONFIG["stack"]:
                with self.subTest(stack=stack):
                    output = root / stack
                    _stamp(output, stack, enable=True)

                    client = output / "local-ollama" / "python" / "local_ollama_client.py"
                    swift = output / "local-ollama" / "swift" / "LocalOllamaClient.swift"
                    doc = output / "docs" / "LOCAL_OLLAMA.md"
                    for path in (client, swift, doc):
                        self.assertTrue(path.is_file(), path)

                    # No unsubstituted tokens anywhere in the stamped add-on tree.
                    for path in (output / "local-ollama").rglob("*"):
                        if path.is_file():
                            self.assertIsNone(
                                LEAK.search(path.read_text(encoding="utf-8", errors="ignore")),
                                f"token leak in {path}",
                            )

                    # Tokens really substituted into both variants.
                    py = client.read_text()
                    self.assertIn('DEFAULT_HOST: str = "127.0.0.1"', py)
                    self.assertIn("DEFAULT_PORT: int = 11434", py)
                    self.assertIn('DEFAULT_MODEL: str = "llama3.2"', py)
                    sw = swift.read_text()
                    self.assertIn('defaultHost = "127.0.0.1"', sw)
                    self.assertIn("defaultPort = 11434", sw)

                    # The three stable endpoints are present in both variants.
                    for endpoint in ("/api/generate", "/api/chat", "/api/embeddings"):
                        self.assertIn(endpoint, py)
                        self.assertIn(endpoint, sw)

                    # The stamped Python client passes its offline self-test.
                    selftest = output / "local-ollama" / "python" / "selftest.py"
                    result = subprocess.run(
                        [sys.executable, "-B", str(selftest)],
                        check=False, capture_output=True, text=True, timeout=60,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("PASS", result.stdout)

    def test_client_is_loopback_first_and_has_no_heavy_deps(self) -> None:
        src = (ADDON / "local-ollama" / "python" / "local_ollama_client.py").read_text()
        # loopback guard present
        self.assertIn("allow_nonloopback", src)
        self.assertIn("EndpointNotAllowedError", src)
        # stdlib only — no third-party HTTP client
        for banned in ("import requests", "import httpx", "import aiohttp"):
            self.assertNotIn(banned, src)


if __name__ == "__main__":
    unittest.main()
