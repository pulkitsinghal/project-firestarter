"""Generator + behaviour contract for the work_registry add-on.

Proves the add-on is off by default, stamps for every declared stack with no
token leaks, that the stamped tool is stdlib-only, and that a claim/check/release
cycle on an isolated registry file behaves as an advisory noticeboard (held by
someone else exits non-zero; held by you exits zero; release frees it).
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
ADDON = ROOT / "addons" / "work_registry" / "common"
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
        args += ["--set", "include_work_registry=yes"]
    subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True)


def _registry(script: Path, registry_file: Path, owner: str, *argv: str):
    env = {
        "WORK_REGISTRY": str(registry_file),
        "WORK_REGISTRY_OWNER": owner,
        "PATH": "/usr/bin:/bin",
    }
    return subprocess.run(
        [sys.executable, "-B", str(script), *argv],
        check=False, capture_output=True, text=True, timeout=60, env=env,
    )


class WorkRegistryContractTests(unittest.TestCase):
    def test_registered_as_closed_choice_and_off_by_default(self) -> None:
        self.assertEqual(CONFIG["include_work_registry"], ["no", "yes"])
        self.assertIn('"work_registry"', GENERATOR.read_text())

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "default"
            _stamp(output, "fastapi-next", enable=False)
            self.assertFalse((output / "tools" / "work_registry").exists())

    def test_tool_is_stdlib_only(self) -> None:
        src = (ADDON / "tools" / "work_registry" / "registry.py").read_text()
        for banned in ("import requests", "import httpx", "import aiohttp", "import yaml"):
            self.assertNotIn(banned, src)

    def test_every_stack_stamps_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for stack in CONFIG["stack"]:
                with self.subTest(stack=stack):
                    output = root / stack
                    _stamp(output, stack, enable=True)

                    script = output / "tools" / "work_registry" / "registry.py"
                    doc = output / "docs" / "WORK_REGISTRY.md"
                    for path in (script, doc):
                        self.assertTrue(path.is_file(), path)

                    for path in (output / "tools" / "work_registry").rglob("*"):
                        if path.is_file():
                            self.assertIsNone(
                                LEAK.search(path.read_text(encoding="utf-8", errors="ignore")),
                                f"token leak in {path}",
                            )

                    subprocess.run(
                        [sys.executable, "-m", "py_compile", str(script)],
                        check=True, capture_output=True, text=True,
                    )

    def test_advisory_claim_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "app"
            _stamp(output, "fastapi-next", enable=True)
            script = output / "tools" / "work_registry" / "registry.py"
            reg = root / "work-registry.json"
            resource = str(root / "some-repo")

            # Free resource: check exits 0.
            self.assertEqual(_registry(script, reg, "alice", "check", resource).returncode, 0)

            # Alice claims it.
            claimed = _registry(script, reg, "alice", "claim", resource, "--intent", "editing")
            self.assertEqual(claimed.returncode, 0, claimed.stdout + claimed.stderr)

            # Bob sees it held: check exits non-zero and names alice.
            bob = _registry(script, reg, "bob", "check", resource)
            self.assertNotEqual(bob.returncode, 0)
            self.assertIn("alice", bob.stdout + bob.stderr)

            # Alice still owns it: check exits 0.
            self.assertEqual(_registry(script, reg, "alice", "check", resource).returncode, 0)

            # Release frees it.
            released = _registry(script, reg, "alice", "release", resource)
            self.assertEqual(released.returncode, 0, released.stdout + released.stderr)
            self.assertEqual(_registry(script, reg, "bob", "check", resource).returncode, 0)


if __name__ == "__main__":
    unittest.main()
