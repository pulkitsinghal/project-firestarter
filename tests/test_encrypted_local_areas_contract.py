"""Generator + fail-closed-guard contract for the encrypted_local_areas add-on."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addons" / "encrypted_local_areas" / "common"
GENERATOR = ROOT / "bin" / "generate.py"

# The five files the add-on stamps into a project (source paths under common/,
# `{{ encrypted_paths }}` resolving to the default area name `private`).
EXPECTED_STAMPED = (
    "private/.gitattributes",
    "private/README.md",
    "scripts/git-crypt-guard.sh",
    ".githooks/pre-commit",
    "docs/ENCRYPTED_LOCAL_AREAS.md",
)


def _stamp(output: Path, *sets: str) -> None:
    args = [sys.executable, str(GENERATOR), "--defaults", "--output", str(output)]
    for s in sets:
        args += ["--set", s]
    subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True)


class EncryptedLocalAreasGeneratorTests(unittest.TestCase):
    def test_default_off_and_registered_as_closed_choice(self) -> None:
        config = json.loads((ROOT / "firestarter.config.json").read_text())
        self.assertEqual(config["include_encrypted_local_areas"], ["no", "yes"])
        # New tokens are declared so substitution stays whitelist-only.
        self.assertEqual(config["encrypted_paths"], "private")
        self.assertIn("password_manager", config)
        # Registered in the generator's add-on overlay loop.
        self.assertIn('"encrypted_local_areas"', GENERATOR.read_text())

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "default"
            _stamp(output)
            self.assertFalse((output / "private").exists())
            self.assertFalse((output / "scripts" / "git-crypt-guard.sh").exists())
            # The template's own pre-commit (base gate) is what ships when off.
            base_hook = (output / ".githooks" / "pre-commit").read_text()
            self.assertNotIn("git-crypt-guard", base_hook)

    def test_every_stack_stamps_the_area_without_token_leaks(self) -> None:
        config = json.loads((ROOT / "firestarter.config.json").read_text())
        with tempfile.TemporaryDirectory() as temp:
            for stack in config["stack"]:
                with self.subTest(stack=stack):
                    output = Path(temp) / stack
                    _stamp(output, f"stack={stack}", "include_encrypted_local_areas=yes")
                    for rel in EXPECTED_STAMPED:
                        self.assertTrue((output / rel).exists(), f"{stack}:{rel}")

                    # Tokens fully substituted (no unresolved {{ ... }} anywhere
                    # in the add-on's stamped files).
                    for rel in EXPECTED_STAMPED:
                        self.assertNotIn("{{", (output / rel).read_text(), f"{stack}:{rel}")

                    # The .gitattributes designates git-crypt and keeps the
                    # plaintext pointers out of the filter.
                    attrs = (output / "private" / ".gitattributes").read_text()
                    self.assertIn("filter=git-crypt diff=git-crypt", attrs)
                    self.assertIn("README.md      !filter !diff", attrs)
                    self.assertIn(".gitattributes !filter !diff", attrs)

                    # The pointer README is plaintext and states the key location
                    # (default password_manager token) + the no-public-remote rule.
                    readme = (output / "private" / "README.md").read_text()
                    self.assertIn("1Password", readme)
                    self.assertIn("PUBLIC remote", readme)

    def test_superset_pre_commit_keeps_the_base_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "hook"
            _stamp(output, "include_encrypted_local_areas=yes")
            hook = (output / ".githooks" / "pre-commit").read_text()
            # Runs the guard AND the base precommit gate (not a replacement).
            self.assertIn("git-crypt-guard.sh", hook)
            self.assertIn("make precommit", hook)

    def test_guard_blocks_plaintext_and_passes_ciphertext(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git not available")

        with tempfile.TemporaryDirectory() as temp:
            stamped = Path(temp) / "gen"
            _stamp(stamped, "include_encrypted_local_areas=yes")
            attrs = (stamped / "private" / ".gitattributes").read_text()
            guard = (stamped / "scripts" / "git-crypt-guard.sh").read_text()

            repo = Path(temp) / "repo"
            (repo / "private").mkdir(parents=True)
            (repo / "private" / ".gitattributes").write_text(attrs)
            (repo / "git-crypt-guard.sh").write_text(guard)

            def git(*a: str) -> None:
                subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True)

            def run_guard() -> int:
                return subprocess.run(
                    ["bash", "git-crypt-guard.sh"], cwd=repo, capture_output=True, text=True
                ).returncode

            git("init")
            git("config", "user.email", "t@e.st")
            git("config", "user.name", "test")

            # 1) A plaintext file inside the encrypted area is REFUSED.
            (repo / "private" / "secret.txt").write_text("TOP SECRET PLAINTEXT\n")
            git("add", "private/.gitattributes", "private/secret.txt")
            self.assertEqual(run_guard(), 1, "guard must block plaintext in an encrypted area")

            # 2) The same path staged as a git-crypt blob (magic header) PASSES,
            #    and the excluded pointer README is never flagged.
            (repo / "private" / "secret.txt").write_bytes(
                b"\x00GITCRYPT\x00" + b"ciphertext-payload"
            )
            (repo / "private" / "README.md").write_text("plaintext pointer, stays readable\n")
            git("add", "private/secret.txt", "private/README.md")
            self.assertEqual(run_guard(), 0, "guard must pass an encrypted blob + excluded pointer")

            # 3) A plaintext file OUTSIDE any encrypted area is not the guard's
            #    business.
            (repo / "notes.md").write_text("ordinary tracked file\n")
            git("add", "notes.md")
            self.assertEqual(run_guard(), 0, "guard must ignore paths outside encrypted areas")


if __name__ == "__main__":
    unittest.main()
