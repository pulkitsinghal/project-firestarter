"""Generator and privacy contract for the agent-eval-harness add-on."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADDON = (
    ROOT
    / "addons"
    / "agent_eval_harness"
    / "common"
    / "tools"
    / "agent_eval_harness"
)
GENERATOR = ROOT / "bin" / "generate.py"


class AgentEvalHarnessGeneratorTests(unittest.TestCase):
    def test_default_off_and_registered_as_closed_choice(self) -> None:
        config = json.loads((ROOT / "firestarter.config.json").read_text())
        self.assertEqual(config["include_agent_eval_harness"], ["no", "yes"])
        generator = GENERATOR.read_text()
        self.assertIn('"agent_eval_harness"', generator)

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "default"
            subprocess.run(
                [
                    sys.executable,
                    str(GENERATOR),
                    "--defaults",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertFalse((output / "tools" / "agent_eval_harness").exists())

    def test_every_stack_stamps_exact_canonical_addon_and_validates(self) -> None:
        config = json.loads((ROOT / "firestarter.config.json").read_text())
        source_files = {
            path.relative_to(ADDON): path.read_bytes()
            for path in ADDON.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        self.assertGreaterEqual(len(source_files), 20)

        with tempfile.TemporaryDirectory() as temp:
            output_root = Path(temp)
            for stack in config["stack"]:
                with self.subTest(stack=stack):
                    output = output_root / stack
                    subprocess.run(
                        [
                            sys.executable,
                            str(GENERATOR),
                            "--defaults",
                            "--set",
                            f"stack={stack}",
                            "--set",
                            "include_agent_eval_harness=yes",
                            "--output",
                            str(output),
                        ],
                        cwd=ROOT,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    generated = output / "tools" / "agent_eval_harness"
                    generated_files = {
                        path.relative_to(generated): path.read_bytes()
                        for path in generated.rglob("*")
                        if path.is_file() and "__pycache__" not in path.parts
                    }
                    self.assertEqual(generated_files, source_files)

            env = os.environ.copy()
            env["PYTHONPATH"] = str(output_root / "fastapi-next")
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "tools.agent_eval_harness.run_validation",
                ],
                cwd=output_root / "fastapi-next",
                env=env,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("agent_eval_harness: PASS", result.stdout)

    def test_contracts_are_closed_and_runtime_has_no_execution_capability(self) -> None:
        for path in (ADDON / "schemas").glob("*.schema.json"):
            schema = json.loads(path.read_text())
            self.assertIs(schema["additionalProperties"], False, path.name)

        forbidden_imports = (
            "import selenium",
            "import playwright",
            "import pyautogui",
            "import pynput",
            "import requests",
            "import socket",
            "import subprocess",
            "import importlib",
            "from urllib",
        )
        forbidden_calls = ("eval(", "exec(", "__import__(")
        runtime = "\n".join(
            path.read_text()
            for path in ADDON.rglob("*.py")
            if "tests" not in path.parts and path.name != "privacy_scan.py"
        )
        for marker in forbidden_imports + forbidden_calls:
            self.assertNotIn(marker, runtime)


if __name__ == "__main__":
    unittest.main()
