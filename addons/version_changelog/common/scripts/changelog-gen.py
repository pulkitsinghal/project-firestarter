#!/usr/bin/env python3
"""Turn git history into a *curated* changelog manifest.

The rule this enforces: nothing reaches users by accident. Commit subjects are
written for engineers and routinely say things like "fix the thing I broke in the
last commit" — true, useful internally, and not what a collaborator should read.

So generation is two-step and fails closed:

  1. `draft`   scan commits between tags, propose entries, mark each `include`
               true only if it is plausibly user-facing (feat/fix, user-facing
               scope, not matching the internal patterns). Everything else lands
               with include=false and the reason why.
  2. `publish` read the (hand- or AI-edited) draft and emit changelog.json with
               ONLY included entries and only user-facing fields. Internal notes,
               commit hashes and rejection reasons never appear in the output.

Rollback availability is not guessed. A version is restorable only if the project
supplies an immutable URL for it in the rollback map — typically a per-deployment
alias that will still serve that exact build years from now. Anything touching
server state stays disabled with a reason the reader can understand.

  ./changelog-gen.py draft   --repo . --out changelog.draft.json
  ./changelog-gen.py publish --draft changelog.draft.json --out changelog.json \
                             --rollback-map rollback.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

# Commit types that can ever be user-facing. Everything else is plumbing.
USER_FACING_TYPES = {"feat", "fix", "perf"}
# Scopes that are plumbing even when the type is feat/fix.
INTERNAL_SCOPES = {"ci", "build", "test", "tests", "deps", "chore", "infra", "tooling"}
# Subjects that describe our own mess rather than the user's experience.
INTERNAL_PATTERNS = [
    re.compile(p, re.I) for p in (
        r"\brevert\b", r"\bwip\b", r"\btypo\b", r"\bbroke[n]?\b", r"\boops\b",
        r"\bregression I\b", r"\bmy (own )?(bug|mistake|fault)\b",
        r"\bstale\b.*\b(slide|build|artifact)\b", r"\bforgot\b", r"\bagain\b$",
    )
]
SUBJECT_RE = re.compile(r"^(?P<type>\w+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s*(?P<subject>.+)$")


def git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def classify(subject: str) -> tuple[bool, str]:
    """Should this line be shown to a user, and if not, why not."""
    m = SUBJECT_RE.match(subject)
    if not m:
        return False, "not a conventional commit"
    typ, scope = m.group("type").lower(), (m.group("scope") or "").lower()
    if typ not in USER_FACING_TYPES:
        return False, f"type '{typ}' is not user-facing"
    if scope in INTERNAL_SCOPES:
        return False, f"scope '{scope}' is internal"
    for pat in INTERNAL_PATTERNS:
        if pat.search(m.group("subject")):
            return False, "reads as internal detail"
    return True, ""


def humanise(subject: str) -> str:
    """Strip the conventional-commit prefix and start with a capital."""
    m = SUBJECT_RE.match(subject)
    text = m.group("subject") if m else subject
    return text[:1].upper() + text[1:]


def releases_from_git(repo: pathlib.Path) -> list[dict]:
    tags = [t for t in git(repo, "tag", "--sort=-creatordate").splitlines() if t.strip()]
    spans: list[tuple[str, str | None]] = []
    if tags:
        for i, tag in enumerate(tags):
            spans.append((tag, tags[i + 1] if i + 1 < len(tags) else None))
    else:
        spans.append(("HEAD", None))

    out = []
    for tag, prev in spans:
        rng = f"{prev}..{tag}" if prev else tag
        log = git(repo, "log", "--no-merges", "--pretty=format:%h%x1f%s%x1f%cI", rng)
        entries = []
        for line in [l for l in log.splitlines() if l.strip()]:
            sha, subject, date = line.split("\x1f")
            include, why = classify(subject)
            entries.append({
                "include": include,
                "text": humanise(subject),
                "_commit": sha,
                "_subject": subject,
                **({"_excluded_because": why} if not include else {}),
            })
        date = git(repo, "log", "-1", "--pretty=format:%cI", tag)[:10] if tag != "HEAD" else ""
        out.append({
            "id": tag,
            "title": tag,
            "date": date,
            "reviewed": False,
            "notes": entries,
        })
    return out


def cmd_draft(args) -> int:
    repo = pathlib.Path(args.repo).resolve()
    data = {
        "_comment": "Draft. Edit titles and note text for a reader who does not work here; "
                    "flip include:true/false as needed. Only included notes are published, and "
                    "fields beginning with _ are never published.",
        "title": args.title,
        "releases": releases_from_git(repo),
    }
    pathlib.Path(args.out).write_text(json.dumps(data, indent=2) + "\n")
    total = sum(len(r["notes"]) for r in data["releases"])
    kept = sum(1 for r in data["releases"] for n in r["notes"] if n["include"])
    print(f"draft written to {args.out}: {len(data['releases'])} releases, "
          f"{kept}/{total} notes proposed for publication")
    return 0


def cmd_publish(args) -> int:
    draft = json.loads(pathlib.Path(args.draft).read_text())
    rollback = json.loads(pathlib.Path(args.rollback_map).read_text()) if args.rollback_map else {}
    default_reason = rollback.get(
        "_default_reason",
        "This version is not available to reopen — it predates the archive.",
    )

    releases, unreviewed = [], []
    for rel in draft.get("releases", []):
        # The include heuristic is a proposal, not a gate. Someone has to have read
        # these lines as a stranger would before they ship.
        if not rel.get("reviewed"):
            unreviewed.append(rel["id"])
            continue
        highlights = [n["text"] for n in rel.get("notes", []) if n.get("include")]
        if not highlights and not args.keep_empty:
            continue
        rb = rollback.get(rel["id"], {})
        releases.append({
            "id": rel["id"],
            "title": rel.get("title") or rel["id"],
            "date": rel.get("date", ""),
            **({"runtime": rel["runtime"]} if rel.get("runtime") else {}),
            "highlights": highlights,
            "rollback": {
                "available": bool(rb.get("url")),
                **({"url": rb["url"]} if rb.get("url") else {}),
                "reason": rb.get("reason", "" if rb.get("url") else default_reason),
            },
        })

    out = {"title": draft.get("title", "Version history"), "releases": releases}
    if draft.get("stampLabel"):
        out["stampLabel"] = draft["stampLabel"]

    leaked = [k for k in json.dumps(out) .split('"') if k.startswith("_")]
    if leaked:
        print(f"refusing to publish: internal fields leaked into output: {sorted(set(leaked))}",
              file=sys.stderr)
        return 1

    if unreviewed:
        print(f"skipped {len(unreviewed)} unreviewed release(s): {', '.join(unreviewed)}\n"
              f"  read their notes as an outsider would, then set reviewed: true",
              file=sys.stderr)
    if not releases:
        print("nothing to publish — no release has been reviewed yet", file=sys.stderr)
        return 1

    pathlib.Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
    restorable = sum(1 for r in releases if r["rollback"]["available"])
    print(f"published {args.out}: {len(releases)} releases, {restorable} restorable")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("draft", help="propose entries from git history")
    d.add_argument("--repo", default=".")
    d.add_argument("--out", default="changelog.draft.json")
    d.add_argument("--title", default="Version history")
    d.set_defaults(fn=cmd_draft)

    q = sub.add_parser("publish", help="emit the user-facing manifest")
    q.add_argument("--draft", default="changelog.draft.json")
    q.add_argument("--out", default="changelog.json")
    q.add_argument("--rollback-map", default=None)
    q.add_argument("--keep-empty", action="store_true",
                   help="keep releases whose notes were all excluded")
    q.set_defaults(fn=cmd_publish)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
