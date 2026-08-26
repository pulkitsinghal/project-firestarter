"""Static privacy and capability-boundary checks for the source-only package.

Three surfaces are scanned:

1. Every runtime ``*.py`` in the package (tests and this file excluded) for
   forbidden network/subprocess imports.
2. Every ``*.synthetic.json`` fixture, walked key-by-key, for identity-shaped
   keys, absolute paths, URLs, hosts, and email/identity-shaped values.
3. The *emitted artifacts*: the golden manifest fixture is loaded and rendered
   to Mermaid and ANATOMY, and both outputs are scanned for absolute paths,
   URLs, hosts, and identity markers.

``scan()`` returns a list of finding strings; an empty list means PASS.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Iterable


ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
GOLDEN_FIXTURE = FIXTURES / "architecture-manifest.synthetic.json"

FORBIDDEN_IMPORTS = (
    r"^\s*(?:from|import)\s+(?:selenium|playwright|pyautogui|pynput|requests|socket|subprocess|http)\b",
    r"^\s*from\s+urllib\b",
)

FORBIDDEN_FIXTURE_KEYS = {
    "url",
    "uri",
    "host",
    "hostname",
    "ip",
    "dsn",
    "connectionString",
    "password",
    "secret",
    "token",
    "email",
    "credential",
}

ABSOLUTE_PATH = re.compile(r"(?:^/)|(?:^[A-Za-z]:[\\/])")
IDENTITY_SHAPE = re.compile(r"://|@|\b\d{1,3}(?:\.\d{1,3}){3}\b")


def _walk(value: object) -> Iterable[tuple[str, object]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _scan_text(source: str, label: str) -> list[str]:
    findings: list[str] = []
    if ABSOLUTE_PATH.search(source):
        findings.append(f"absolute path in emitted artifact: {label}")
    if IDENTITY_SHAPE.search(source):
        findings.append(f"network or identity marker in emitted artifact: {label}")
    return findings


def scan() -> list[str]:
    findings: list[str] = []

    for path in sorted(ROOT.rglob("*.py")):
        if path.name == "privacy_scan.py" or "tests" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_IMPORTS:
            if re.search(pattern, source, flags=re.MULTILINE):
                findings.append(f"forbidden runtime import in {path.relative_to(ROOT)}")

    for fixture_path in sorted(FIXTURES.glob("*.synthetic.json")):
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        for key, value in _walk(fixture):
            if key in FORBIDDEN_FIXTURE_KEYS:
                findings.append(f"forbidden fixture key: {key} in {fixture_path.name}")
            if isinstance(value, str):
                # Evidence paths legitimately contain "/" and "."; only flag the
                # unambiguous leak shapes (absolute, scheme, host, identity).
                if ABSOLUTE_PATH.search(value) or IDENTITY_SHAPE.search(value):
                    findings.append(
                        f"identity-shaped value under {key} in {fixture_path.name}"
                    )

    # Emitted-artifact scan: render the golden manifest and inspect the output.
    if GOLDEN_FIXTURE.exists():
        from .manifest import load_manifest
        from .render import render_anatomy, render_mermaid

        manifest = load_manifest(json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8")))
        findings.extend(_scan_text(render_mermaid(manifest), "mermaid"))
        findings.extend(_scan_text(render_anatomy(manifest), "anatomy"))

    return findings


def main() -> int:
    findings = scan()
    if findings:
        for finding in findings:
            print(f"FAIL {finding}")
        return 1
    print("privacy-scan: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
