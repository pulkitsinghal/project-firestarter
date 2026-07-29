#!/usr/bin/env python3
"""Run the plugin's deterministic local acceptance suite."""

from __future__ import annotations

import compileall
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if not compileall.compile_dir(ROOT, quiet=1, force=True):
        print("Python compile: FAIL", file=sys.stderr)
        return 1
    tests = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        check=False,
    )
    if tests.returncode:
        return tests.returncode
    privacy = subprocess.run(
        [sys.executable, str(ROOT / "scripts/privacy_scan.py")],
        cwd=ROOT,
        check=False,
    )
    return privacy.returncode


if __name__ == "__main__":
    raise SystemExit(main())
