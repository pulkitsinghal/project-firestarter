#!/usr/bin/env python3
"""
Project Firestarter — cookiecutter-style generator (stdlib only, no pip).

Stamps a new project from `template/` (the universal meta-layer) overlaid with
the chosen `stacks/<stack>/` profile, substituting `{{ token }}` placeholders
declared in `firestarter.config.json`.

Honours the "no host SDKs" rule: this runs inside a python:slim container via
`bin/firestart.sh`, so nothing is installed on the host. It can also be run
directly with any Python 3.8+ if you already have one.

Usage (via the wrapper — recommended):
    ./bin/firestart.sh                         # interactive prompts
    ./bin/firestart.sh --defaults              # accept every default
    ./bin/firestart.sh --set project_name="Project Pilgrim" --set stack=supabase-flutter
    ./bin/firestart.sh --values my-answers.json --output ../project-pilgrim

Token safety: only the exact keys declared in firestarter.config.json are
substituted, so GitHub Actions expressions like ${{ github.sha }} are never
touched.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "firestarter.config.json"


def load_config() -> dict:
    raw = json.loads(CONFIG_PATH.read_text())
    # Drop documentation keys (anything starting with "_").
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def render(text: str, values: dict) -> str:
    """Replace {{ key }} for each known key. Whitelist-only: unknown braces
    (including GitHub's ${{ ... }}) are left untouched."""
    for key, val in values.items():
        text = re.sub(r"\{\{\s*" + re.escape(key) + r"\s*\}\}", str(val), text)
    return text


def derive(values: dict) -> dict:
    """Compute tokens that are functions of the user's answers, so templates
    can stay free of conditionals."""
    slug = values["project_slug"]
    values["migrations_table"] = f"{slug}_migrations"
    values["pgdata_volume"] = f"{slug}_pgdata"
    values["container_prefix"] = slug

    if values.get("require_coauthor") == "yes":
        footer = values.get("coauthor_footer", "").strip()
        values["coauthor_policy"] = (
            "Co-author footer **required**. Append this line to every commit:\n\n"
            f"    {footer}"
        )
        values["coauthor_commit_footer"] = footer
    else:
        values["coauthor_policy"] = "No co-author footer is required on this project."
        values["coauthor_commit_footer"] = ""
    return values


def prompt(key: str, default, choices=None) -> str:
    if choices:
        opts = "/".join(choices)
        ans = input(f"  {key} [{opts}] ({default}): ").strip()
        if not ans:
            return default
        if ans not in choices:
            print(f"    '{ans}' is not one of {choices}; using '{default}'.")
            return default
        return ans
    ans = input(f"  {key} ({default}): ").strip()
    return ans or default


def collect(config: dict, args) -> dict:
    overrides = dict(args.set or [])
    if args.values:
        overrides.update(json.loads(Path(args.values).read_text()))

    values: dict = {}
    interactive = (not args.defaults) and sys.stdin.isatty() and not overrides.get("__noninteractive__")

    print("\nProject Firestarter — answer a few questions (Enter accepts the default):\n"
          if interactive else "\nProject Firestarter — resolving values:\n")

    for key, spec in config.items():
        choices = spec if isinstance(spec, list) else None
        default = (choices[0] if choices else render(str(spec), values))

        if key in overrides:
            values[key] = overrides[key]
        elif interactive:
            values[key] = prompt(key, default, choices)
        else:
            values[key] = default

        if not interactive:
            print(f"  {key} = {values[key]}")

    return derive(values)


def is_binary(path: Path) -> bool:
    try:
        path.read_text(encoding="utf-8")
        return False
    except (UnicodeDecodeError, ValueError):
        return True


def stamp(src_root: Path, out_root: Path, values: dict) -> int:
    written = 0
    for dirpath, dirnames, filenames in os.walk(src_root):
        dirnames.sort()
        for name in sorted(filenames):
            src = Path(dirpath) / name
            rel = src.relative_to(src_root)
            dest_rel = Path(*[render(part, values) for part in rel.parts])
            dest = out_root / dest_rel
            dest.parent.mkdir(parents=True, exist_ok=True)

            if is_binary(src):
                shutil.copy2(src, dest)
            else:
                dest.write_text(render(src.read_text(encoding="utf-8"), values), encoding="utf-8")

            # Make hooks and shell scripts executable.
            in_hooks = ".githooks" in dest_rel.parts
            if dest.suffix == ".sh" or (in_hooks and dest.suffix == ""):
                dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            written += 1
    return written


def main() -> int:
    config = load_config()

    p = argparse.ArgumentParser(description="Stamp a new project from the firestarter template.")
    p.add_argument("--output", "-o", help="Output directory (default: ../<github_repo>)")
    p.add_argument("--values", help="JSON file of answers (overrides defaults/prompts)")
    p.add_argument("--set", action="append", metavar="key=value",
                   type=lambda kv: tuple(kv.split("=", 1)),
                   help="Set a single value (repeatable)")
    p.add_argument("--defaults", action="store_true", help="Non-interactive; use all defaults")
    p.add_argument("--force", action="store_true", help="Allow writing into a non-empty output dir")
    args = p.parse_args()

    values = collect(config, args)

    stack = values["stack"]
    stack_dir = ROOT / "stacks" / stack
    if not stack_dir.is_dir():
        avail = ", ".join(sorted(d.name for d in (ROOT / "stacks").iterdir() if d.is_dir()))
        print(f"\n✗ Unknown stack '{stack}'. Available: {avail}")
        return 2

    out_root = Path(args.output) if args.output else ROOT.parent / values["github_repo"]
    out_root = out_root.resolve()

    if out_root.exists() and any(out_root.iterdir()) and not args.force:
        print(f"\n✗ Output dir {out_root} is not empty. Re-run with --force to overlay.")
        return 2

    print(f"\nStamping → {out_root}\n  stack: {stack}")
    out_root.mkdir(parents=True, exist_ok=True)

    n = stamp(ROOT / "template", out_root, values)
    n += stamp(stack_dir, out_root, values)

    # Optional add-ons: overlay addons/<name>/<stack>/ when the matching
    # include_<name> flag is "yes". Keeps opinionated/heavy modules (e.g. k8s)
    # out of the default scaffold.
    for addon in ("k8s", "auth", "bug_report", "ssrf_fetch"):
        if values.get(f"include_{addon}") == "yes":
            addon_dir = ROOT / "addons" / addon / stack
            if addon_dir.is_dir():
                n += stamp(addon_dir, out_root, values)
                print(f"  + addon: {addon}")
            else:
                print(f"  (addon '{addon}' has no profile for stack '{stack}', skipped)")

    print(f"\n✓ Wrote {n} files.\n")
    print("Next steps:")
    print(f"  cd {out_root}")
    print("  git init && git add -A && git commit -m 'chore: scaffold from firestarter'")
    print("  make hook-install        # activate the opt-in git hooks")
    print("  make up && make migrate  # boot the stack")
    print("  gh secret set ANTHROPIC_API_KEY   # enable the AI PR reviewer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
