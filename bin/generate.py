#!/usr/bin/env python3
"""
Project Firestarter: cookiecutter-style generator (stdlib only, no pip).

Stamps a new project from `template/` (the universal meta-layer) overlaid with
the chosen `stacks/<stack>/` profile, substituting `{{ token }}` placeholders
declared in `firestarter.config.json`.

Honours the "no host SDKs" rule: this runs inside a python:slim container via
`bin/firestart.sh`, so nothing is installed on the host. It can also be run
directly with any Python 3.8+ if you already have one.

Usage (via the wrapper, recommended):
    ./bin/firestart.sh                         # interactive prompts
    ./bin/firestart.sh --defaults              # accept every default
    ./bin/firestart.sh --set project_name="Project Acme" --set stack=supabase-flutter
    ./bin/firestart.sh --values my-answers.json --output ../project-x

Overlay roots (private companion layers):
    ./bin/firestart.sh --overlay ../firestarter-private        # repeatable
    FIRESTARTER_PRIVATE=../firestarter-private ./bin/firestart.sh
Each overlay dir may carry its own `addons/<name>/{common,<stack>}/` trees and an
optional `firestarter.config.json` *fragment*. Fragments are merged over the base
config (overlay wins; later overlays win over earlier ones), and addon lookup
searches the base `addons/` first, then each overlay's `addons/`. The content of
every overlay stays out of this public repo; only this generic mechanism lives here.

Token safety: only the exact keys declared in firestarter.config.json (or in a
merged overlay fragment) are substituted, so GitHub Actions expressions like
${{ github.sha }} are never touched. Overlay-declared keys become valid tokens
without broadening the whitelist to "replace any {{ }}".
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
GITHUB_REPOSITORY_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9._-]{1,100}$"
)
PROJECT_SLUG_RE = re.compile(r"^[a-z](?:[a-z0-9-]{0,38}[a-z0-9])?$")


# Optional add-ons shipped in this public repo. Overlay roots may declare more
# via their own `include_<name>` config keys; those are discovered at runtime.
BASE_ADDONS = (
    "k8s",
    "auth",
    "bug_report",
    "ssrf_fetch",
    "scheduled_agent",
    "kokoro_warm",
    "secret_vault",
    "orchestrator_session",
    "service_supervisor",
    "bounded_runner",
    "browser_automation_policy",
    "local_ollama",
    "encrypted_local_areas",
    "convergent_deploy",
    "cross_host_agent",
    "version_changelog",
    "trusted_workstation",
    "agent_eval_harness",
    "reviewed_extraction",
    "mcp_security_gate",
    "architecture_manifest",
    "datastore_advisor",
    "work_registry",
)


def load_config_file(path: Path) -> dict:
    raw = json.loads(path.read_text())
    # Drop documentation keys (anything starting with "_").
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def load_config() -> dict:
    return load_config_file(CONFIG_PATH)


def resolve_overlays(args) -> list:
    """Collect overlay roots from --overlay (repeatable) then the
    FIRESTARTER_PRIVATE env (os.pathsep-separated). Relative paths resolve
    against the current working directory; later overlays win over earlier."""
    raw: list = list(args.overlay or [])
    env = os.environ.get("FIRESTARTER_PRIVATE", "").strip()
    if env:
        raw += [part for part in env.split(os.pathsep) if part]

    resolved: list = []
    for entry in raw:
        path = Path(entry).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"overlay root not found: {entry} (resolved to {path})")
        if path not in resolved:
            resolved.append(path)
    return resolved


def merge_overlay_config(base: dict, overlays: list) -> dict:
    """Merge each overlay's firestarter.config.json fragment over the base.
    Overlay wins per key; keys new to an overlay are appended (so they become
    valid tokens) while the whitelist-only substitution rule is preserved."""
    config = dict(base)
    for overlay in overlays:
        fragment_path = overlay / "firestarter.config.json"
        if fragment_path.is_file():
            config.update(load_config_file(fragment_path))
    return config


def addon_names(config: dict) -> list:
    """Base add-ons first (keeps their names as literals in this file for the
    contract tests), then any extra `include_<name>` flags an overlay declared,
    in config order."""
    names = list(BASE_ADDONS)
    for key in config:
        if key.startswith("include_"):
            name = key[len("include_"):]
            if name not in names:
                names.append(name)
    return names


def render(text: str, values: dict) -> str:
    """Replace {{ key }} for each known key. Whitelist-only: unknown braces
    (including GitHub's ${{ ... }}) are left untouched."""
    for key, val in values.items():
        # A callback makes the value literal: backslashes and replacement-group
        # syntax in user input are never interpreted by the regex engine.
        replacement = str(val)
        text = re.sub(
            r"\{\{\s*" + re.escape(key) + r"\s*\}\}",
            lambda _match, value=replacement: value,
            text,
        )
    return text


def derive(values: dict) -> dict:
    """Compute tokens that are functions of the user's answers, so templates
    can stay free of conditionals."""
    slug = values["project_slug"]
    values["migrations_table"] = f"{slug.replace('-', '_')}_migrations"
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


def validate_values(values: dict) -> None:
    """Reject values whose syntax is security-sensitive in generated output."""
    slug = values.get("project_slug")
    if not isinstance(slug, str) or not PROJECT_SLUG_RE.fullmatch(slug):
        raise ValueError(
            "project_slug must be 1-40 lowercase letters, digits, or hyphens; "
            "it must start with a letter and end with a letter or digit"
        )
    repository = values.get("trusted_workstation_repo")
    if not isinstance(repository, str) or not GITHUB_REPOSITORY_RE.fullmatch(repository):
        raise ValueError(
            "trusted_workstation_repo must use GitHub owner/repository syntax"
        )
    owner, repo = repository.split("/", 1)
    if owner.startswith("-") or owner.endswith("-") or repo in {".", ".."}:
        raise ValueError(
            "trusted_workstation_repo must use GitHub owner/repository syntax"
        )


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

    print("\nProject Firestarter: answer a few questions (Enter accepts the default):\n"
          if interactive else "\nProject Firestarter: resolving values:\n")

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
            # JSON string encoding keeps terminal controls out of generator logs.
            print(f"  {key} = {json.dumps(str(values[key]), ensure_ascii=True)}")

    values = derive(values)
    validate_values(values)
    return values


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
            source_executable = bool(
                src.stat().st_mode
                & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            )
            rel = src.relative_to(src_root)
            dest_rel = Path(*[render(part, values) for part in rel.parts])
            dest = out_root / dest_rel
            dest.parent.mkdir(parents=True, exist_ok=True)

            if is_binary(src):
                shutil.copy2(src, dest)
            else:
                dest.write_text(render(src.read_text(encoding="utf-8"), values), encoding="utf-8")

            # Preserve explicit source executability and keep generated hooks/shell runnable.
            in_hooks = ".githooks" in dest_rel.parts
            if (
                source_executable
                or dest.suffix == ".sh"
                or (in_hooks and dest.suffix == "")
            ):
                dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            written += 1
    return written


def main() -> int:
    p = argparse.ArgumentParser(description="Stamp a new project from the firestarter template.")
    p.add_argument("--output", "-o", help="Output directory (default: ../<github_repo>)")
    p.add_argument("--values", help="JSON file of answers (overrides defaults/prompts)")
    p.add_argument("--set", action="append", metavar="key=value",
                   type=lambda kv: tuple(kv.split("=", 1)),
                   help="Set a single value (repeatable)")
    p.add_argument("--overlay", action="append", metavar="DIR",
                   help="Overlay root with its own addons/ and optional config "
                        "fragment (repeatable; also FIRESTARTER_PRIVATE env)")
    p.add_argument("--defaults", action="store_true", help="Non-interactive; use all defaults")
    p.add_argument("--force", action="store_true", help="Allow writing into a non-empty output dir")
    args = p.parse_args()

    try:
        overlays = resolve_overlays(args)
    except ValueError as exc:
        print(f"\n✗ {exc}")
        return 2
    config = merge_overlay_config(load_config(), overlays)
    if overlays:
        print("Overlay roots (private layers, highest priority last):")
        for overlay in overlays:
            print(f"  · {overlay}")

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

    # Optional add-ons: overlay addons/<name>/common/ (stack-agnostic) then
    # addons/<name>/<stack>/ (stack-specific) when the matching include_<name>
    # flag is "yes". Keeps opinionated/heavy modules (e.g. k8s) out of the default
    # scaffold. The `common/` overlay lets a stack-agnostic add-on live in one
    # place instead of being duplicated under every stack.
    #
    # Add-on lookup searches the base `addons/` first, then each overlay root's
    # `addons/`, so an overlay can ship its own private add-ons (and, because a
    # later root is stamped last, override files of a base add-on it shares a
    # name with). `include_<name>` flags an overlay declared are honoured too.
    addon_roots = [ROOT] + overlays
    for addon in addon_names(config):
        if values.get(f"include_{addon}") == "yes":
            overlaid = False
            for root in addon_roots:
                for sub in ("common", stack):
                    addon_dir = root / "addons" / addon / sub
                    if addon_dir.is_dir():
                        n += stamp(addon_dir, out_root, values)
                        overlaid = True
            if overlaid:
                print(f"  + addon: {addon}")
            else:
                print(f"  (addon '{addon}' has no profile for stack '{stack}', skipped)")

    if values.get("include_trusted_workstation") == "yes":
        # Runtime data is serialized here instead of interpolated into executable
        # shell/PowerShell/JavaScript source or hand-escaped JSON templates.
        repository_file = out_root / "trusted-workstation" / "repository.txt"
        repository_file.write_text(
            values["trusted_workstation_repo"] + "\n", encoding="ascii", newline="\n"
        )
        schema_file = out_root / "trusted-workstation" / "enrollment-ledger.schema.json"
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
        schema["properties"]["repository"]["const"] = values["trusted_workstation_repo"]
        schema_file.write_text(
            json.dumps(schema, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        n += 1

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
