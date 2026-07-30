#!/usr/bin/env python3
"""Static privacy and arbitrary-execution scan for the source artifact."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".md", ".json", ".py", ".yaml", ".yml", ".txt", ""}
FORBIDDEN_TEXT = [
    "[TODO:",
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
]
# Owner-neutral PII heuristics: flag real home-directory paths and
# real-looking personal email addresses, while ignoring the reserved
# example/test domains used in fixtures (RFC 2606). Keep this guard generic
# rather than hard-coding any maintainer's identity into a public artifact.
FORBIDDEN_PATTERNS = [
    re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@(?!example\.)(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b"),
]
FORBIDDEN_CODE = [
    re.compile(r"\bshell\s*=\s*True\b"),
    re.compile(r"\bos\.system\s*\("),
    re.compile(r"\bsubprocess\.(?:call|Popen)\s*\([^\\n]*shell"),
    re.compile(r"\beval\s*\("),
]


def main() -> int:
    failures: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if (
            not path.is_file()
            or path.resolve() == Path(__file__).resolve()
            or "__pycache__" in path.parts
            or path.suffix not in TEXT_SUFFIXES
        ):
            continue
        text = path.read_text(encoding="utf-8", errors="strict")
        relative = path.relative_to(ROOT)
        for needle in FORBIDDEN_TEXT:
            if needle in text:
                failures.append(f"{relative}: forbidden text {needle!r}")
        for pattern in FORBIDDEN_PATTERNS:
            if pattern.search(text):
                failures.append(f"{relative}: forbidden PII pattern {pattern.pattern!r}")
        if path.suffix == ".py":
            for pattern in FORBIDDEN_CODE:
                if pattern.search(text):
                    failures.append(f"{relative}: forbidden execution pattern {pattern.pattern!r}")

    manifest_path = ROOT / ".codex-plugin/plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for unsupported in ("hooks", "apps", "mcpServers"):
        if unsupported in manifest:
            failures.append(f".codex-plugin/plugin.json: unexpected {unsupported}")
    hooks_path = ROOT / "hooks/hooks.json"
    if not hooks_path.is_file():
        failures.append("default hooks/hooks.json missing")
    else:
        try:
            hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
            entries = hooks["hooks"]["PreToolUse"]
            hook = entries[0]["hooks"][0]
            expected_command = (
                'python3 "$PLUGIN_ROOT/hooks/pre_tool_use_root_guard.py"'
            )
            if len(entries) != 1 or entries[0].get("matcher") != "*":
                failures.append("PreToolUse matcher must be one catch-all entry")
            if hook.get("type") != "command" or hook.get("command") != expected_command:
                failures.append("hook command must be confined to bundled adapter")
            if hook.get("timeout") != 5:
                failures.append("hook timeout must remain bounded at 5 seconds")
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            failures.append("hooks/hooks.json is structurally invalid")
    marketplace = ROOT.parents[1] / ".agents/plugins/marketplace.json"
    if not marketplace.is_file():
        failures.append("repo-local marketplace missing")
    else:
        value = json.loads(marketplace.read_text(encoding="utf-8"))
        entries = [item for item in value.get("plugins", []) if item.get("name") == "pm-proxy-orchestrator"]
        if len(entries) != 1:
            failures.append("marketplace must contain exactly one plugin entry")
        else:
            entry = entries[0]
            if entry.get("source") != {
                "source": "local",
                "path": "./plugins/pm-proxy-orchestrator",
            }:
                failures.append("marketplace source path is incompatible")
            if entry.get("policy") != {
                "installation": "AVAILABLE",
                "authentication": "ON_INSTALL",
            }:
                failures.append("marketplace policy is incompatible")
            if entry.get("category") != "Productivity":
                failures.append("marketplace category is incompatible")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("privacy/source scan: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
