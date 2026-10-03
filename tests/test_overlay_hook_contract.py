"""Contract for the external-overlay hook in bin/generate.py.

Proves the generic mechanism that lets the generator pull add-ons and config
from one or more external overlay roots (so a private companion repo can layer
its own add-ons on top of the public scaffold) without putting any private
content, or any non-whitelist substitution, into this public repo.

Covers:
  * an overlay-only add-on (common + stack-specific) stamps alongside the base,
  * an overlay config fragment is merged over the base (overlay wins) and its
    newly declared keys become valid tokens,
  * whitelist-only token safety survives (GitHub ${{ ... }} is untouched),
  * both the --overlay flag (repeatable) and the FIRESTARTER_PRIVATE env work,
  * no overlay means no behaviour change (the base still stamps, no leaks),
  * a missing overlay root fails closed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "bin" / "generate.py"
CONFIG = json.loads((ROOT / "firestarter.config.json").read_text())

# The only legitimate "{{" in generated output is a GitHub expression or JSX.
LEAK = re.compile(r"\{\{")

OVERLAY_ADDON = "demo_overlay"
OVERLAY_TOKEN_VALUE = "OVERLAY_VALUE_7f3a2b"
OVERLAY_OWNER = "overlay-owner-acme"
GITHUB_EXPR = "${{ github.sha }}"


def _write_overlay(root: Path, stack: str) -> None:
    """Materialise a throwaway overlay root: a config fragment plus an
    overlay-only add-on with a stack-agnostic and a stack-specific file."""
    fragment = {
        "_comment": "throwaway overlay fragment for the contract test",
        # Override a base key: the overlay must win.
        "github_owner": OVERLAY_OWNER,
        # A brand-new key: it must become a valid, substitutable token.
        "overlay_marker": OVERLAY_TOKEN_VALUE,
        # A brand-new include_<name> flag the base repo never heard of.
        f"include_{OVERLAY_ADDON}": ["yes", "no"],
    }
    (root / "firestarter.config.json").write_text(
        json.dumps(fragment, indent=2) + "\n", encoding="utf-8"
    )

    common = root / "addons" / OVERLAY_ADDON / "common" / "overlay-proof"
    common.mkdir(parents=True)
    # Exercises: overlay token, base token, overridden base token, and a GitHub
    # expression that must pass through untouched.
    (common / "marker.txt").write_text(
        "marker={{ overlay_marker }} slug={{ project_slug }} "
        f"owner={{{{ github_owner }}}} gh={GITHUB_EXPR}\n",
        encoding="utf-8",
    )

    stack_dir = root / "addons" / OVERLAY_ADDON / stack / "overlay-proof"
    stack_dir.mkdir(parents=True)
    (stack_dir / "stack.txt").write_text(
        "stack-specific for {{ stack }}\n", encoding="utf-8"
    )


def _is_text(path: Path) -> bool:
    try:
        path.read_text(encoding="utf-8")
        return True
    except (UnicodeDecodeError, ValueError):
        return False


def _run(output: Path, stack: str, *, overlay: Path | None, use_env: bool,
         addon: str | None) -> subprocess.CompletedProcess:
    args = [
        sys.executable, "-B", str(GENERATOR), "--defaults",
        "--set", f"stack={stack}",
        "--set", "project_slug=overlayproof",
        "--set", "github_repo=overlay-proof-project",
        "--output", str(output),
    ]
    if addon is not None:
        args += ["--set", f"include_{OVERLAY_ADDON}={addon}"]
    env = dict(os.environ)
    env.pop("FIRESTARTER_PRIVATE", None)
    if overlay is not None:
        if use_env:
            env["FIRESTARTER_PRIVATE"] = str(overlay)
        else:
            args += ["--overlay", str(overlay)]
    return subprocess.run(
        args, cwd=ROOT, check=True, capture_output=True, text=True, env=env, timeout=120
    )


class OverlayHookContractTests(unittest.TestCase):
    def _assert_overlay_landed(self, output: Path, stack: str) -> None:
        marker = output / "overlay-proof" / "marker.txt"
        stack_file = output / "overlay-proof" / "stack.txt"
        self.assertTrue(marker.is_file(), marker)
        self.assertTrue(stack_file.is_file(), stack_file)

        text = marker.read_text()
        # Overlay-declared token substituted.
        self.assertIn(f"marker={OVERLAY_TOKEN_VALUE}", text)
        # Base token substituted.
        self.assertIn("slug=overlayproof", text)
        # Overlay fragment overrode the base github_owner value.
        self.assertIn(f"owner={OVERLAY_OWNER}", text)
        # Whitelist-only safety: the GitHub expression is left untouched.
        self.assertIn(f"gh={GITHUB_EXPR}", text)

        self.assertIn(f"stack-specific for {stack}", stack_file.read_text())

    def test_overlay_flag_stamps_overlay_addon_and_merges_config(self) -> None:
        stack = "fastapi-next"
        with tempfile.TemporaryDirectory() as temp:
            overlay = Path(temp) / "firestarter-private"
            overlay.mkdir()
            _write_overlay(overlay, stack)
            output = Path(temp) / "out"

            result = _run(output, stack, overlay=overlay, use_env=False, addon="yes")
            self.assertIn(f"+ addon: {OVERLAY_ADDON}", result.stdout)
            self._assert_overlay_landed(output, stack)

    def test_overlay_via_env_var(self) -> None:
        stack = "fastapi-next"
        with tempfile.TemporaryDirectory() as temp:
            overlay = Path(temp) / "firestarter-private"
            overlay.mkdir()
            _write_overlay(overlay, stack)
            output = Path(temp) / "out"

            result = _run(output, stack, overlay=overlay, use_env=True, addon="yes")
            self.assertIn(f"+ addon: {OVERLAY_ADDON}", result.stdout)
            self._assert_overlay_landed(output, stack)

    def test_overlay_addon_off_when_flag_is_no(self) -> None:
        stack = "fastapi-next"
        with tempfile.TemporaryDirectory() as temp:
            overlay = Path(temp) / "firestarter-private"
            overlay.mkdir()
            _write_overlay(overlay, stack)
            output = Path(temp) / "out"
            # Overlay present and its flag declared, but answered "no".
            _run(output, stack, overlay=overlay, use_env=False, addon="no")
            self.assertFalse((output / "overlay-proof").exists())

    def test_no_overlay_is_unchanged_and_leak_free(self) -> None:
        # Base generation with no overlay must still work and leak nothing;
        # the overlay-only add-on must be absent.
        with tempfile.TemporaryDirectory() as temp:
            for stack in CONFIG["stack"]:
                with self.subTest(stack=stack):
                    output = Path(temp) / stack
                    _run(output, stack, overlay=None, use_env=False, addon=None)
                    self.assertFalse((output / "overlay-proof").exists())
                    for path in output.rglob("*"):
                        if path.is_file() and not path.is_symlink() and _is_text(path):
                            content = path.read_text(encoding="utf-8")
                            # Allow only GitHub ${{ }} and JSX style={{ }}.
                            stripped = re.sub(r"\$\{\{|style=\{\{", "", content)
                            self.assertIsNone(
                                LEAK.search(stripped), f"token leak in {path}"
                            )

    def test_missing_overlay_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "out"
            result = subprocess.run(
                [sys.executable, "-B", str(GENERATOR), "--defaults",
                 "--set", "stack=fastapi-next",
                 "--overlay", str(Path(temp) / "does-not-exist"),
                 "--output", str(output)],
                cwd=ROOT, capture_output=True, text=True, timeout=120,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("overlay root not found", result.stdout + result.stderr)

    def test_mechanism_is_generic_no_private_names_in_repo(self) -> None:
        # The public repo must carry only the generic hook, never the private
        # overlay's content or name.
        src = GENERATOR.read_text()
        self.assertIn("--overlay", src)
        self.assertIn("FIRESTARTER_PRIVATE", src)
        # No private overlay's add-on names or content baked into the public
        # generator (the conventional `../firestarter-private` example path is
        # fine; it is generic and carries no private content).
        self.assertNotIn("secret_injection", src)
        self.assertNotIn("gcloud secrets", src)


if __name__ == "__main__":
    unittest.main()
