"""Static privacy and capability-boundary checks for the source-only package.

Guarantees the add-on stays deterministic and offline: no networking, no
subprocess, no browser/automation libraries, and no fixture that smuggles a
real endpoint, credential, token, or identity across the static boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Iterable


ROOT = Path(__file__).resolve().parent
FIXTURE_DIR = ROOT / "fixtures"

FORBIDDEN_IMPORTS = (
    r"^\s*(?:from|import)\s+(?:selenium|playwright|pyautogui|pynput|requests|socket|subprocess|http|ftplib|smtplib|asyncio)\b",
    r"^\s*from\s+urllib\.request\b",
    r"^\s*from\s+http\b",
)

FORBIDDEN_FIXTURE_KEYS = {
    "url",
    "uri",
    "host",
    "hostname",
    "path",
    "query",
    "endpoint",
    "token",
    "accessToken",
    "bearer",
    "secret",
    "credential",
    "password",
    "apiKey",
    "cookie",
    "header",
    "authorization",
    "email",
    "logLine",
    "payload",
    "responseBody",
}


def _walk(value: object) -> Iterable[tuple[str, object]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def scan() -> list[str]:
    findings: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        if path.name == "privacy_scan.py" or "tests" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_IMPORTS:
            if re.search(pattern, source, flags=re.MULTILINE):
                findings.append(f"forbidden runtime import in {path.relative_to(ROOT)}")

    for fixture_path in sorted(FIXTURE_DIR.glob("*.synthetic.json")):
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        if fixture.get("syntheticOnly") is not True:
            findings.append(f"fixture not marked synthetic-only: {fixture_path.name}")
        for key, value in _walk(fixture):
            if key in FORBIDDEN_FIXTURE_KEYS:
                findings.append(f"forbidden fixture key: {key}")
            if isinstance(value, str) and (
                "://" in value or re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value)
            ):
                findings.append(f"network or identity-shaped fixture value under {key}")
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
