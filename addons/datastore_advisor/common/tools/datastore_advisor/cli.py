#!/usr/bin/env python3
"""Datastore advisor CLI.

    python3 -m tools.datastore_advisor.cli                       # interactive
    python3 -m tools.datastore_advisor.cli --answers a.json       # non-interactive
    python3 -m tools.datastore_advisor.cli --answers a.json --json
    python3 -m tools.datastore_advisor.cli --answers a.json -o docs/DATASTORE_DECISION.md
    python3 -m tools.datastore_advisor.cli --explain postgres     # read one entry

Interactive mode prints each axis with *why it matters* before the options,
because the reasoning is the part worth having. "unknown" is accepted on any
axis that allows it and is reported back as a measurement task rather than
silently defaulted.

Standard library only, Python 3.8+.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # package-relative when run as a module
    from .advisor import (
        UNKNOWN,
        load_catalog,
        load_questions,
        evaluate,
        render_markdown,
    )
except ImportError:  # direct-script fallback
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from advisor import (  # type: ignore[no-redef]
        UNKNOWN,
        load_catalog,
        load_questions,
        evaluate,
        render_markdown,
    )

RULE = "-" * 72


def _wrap(text: str, width: int = 72, indent: str = "") -> str:
    words = text.split()
    lines: List[str] = []
    cur = indent
    for w in words:
        if len(cur) + len(w) + 1 > width and cur.strip():
            lines.append(cur.rstrip())
            cur = indent + w + " "
        else:
            cur += w + " "
    if cur.strip():
        lines.append(cur.rstrip())
    return "\n".join(lines)


def _axis_applies(axis: Dict[str, Any], answers: Dict[str, Any]) -> bool:
    cond = axis.get("asked_when")
    if not cond:
        return True
    for key, wanted in cond.items():
        given = answers.get(key)
        given_list = given if isinstance(given, (list, tuple)) else [given]
        if not any(w in given_list for w in wanted):
            return False
    return True


def ask(axis: Dict[str, Any]) -> Any:
    print("")
    print(RULE)
    print(axis["title"])
    print(RULE)
    print(_wrap(axis["why_it_matters"]))
    if axis.get("measure_hint"):
        print("")
        print(_wrap("How to measure: " + axis["measure_hint"]))
    print("")
    options = axis["options"]
    for i, opt in enumerate(options, 1):
        print("  " + str(i) + ") " + opt["label"])
    multi = axis.get("multi", False)
    if axis.get("unknown_ok", False):
        print("  ?) I do not know yet")
    hint = "numbers separated by commas" if multi else "a number"
    raw = input("\n  Choose " + hint + ": ").strip()

    if raw in ("?", ""):
        if axis.get("unknown_ok", False):
            return UNKNOWN
        print("  This axis needs an answer.")
        return ask(axis)

    picks: List[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part.isdigit() or not (1 <= int(part) <= len(options)):
            print("  '" + part + "' is not one of the options.")
            return ask(axis)
        picks.append(options[int(part) - 1]["id"])
    if not multi:
        return picks[0]
    return picks


def interactive(questions: Dict[str, Any]) -> Dict[str, Any]:
    answers: Dict[str, Any] = {}
    print("")
    print("Datastore advisor")
    print("")
    print(_wrap(
        "This produces an argument, not a verdict. It will tell you what it "
        "recommends, why, what the case against it is, and what would change the "
        "answer. You make the call."
    ))
    for axis in sorted(questions["axes"], key=lambda a: a["order"]):
        if not _axis_applies(axis, answers):
            continue
        answers[axis["id"]] = ask(axis)
    return answers


def explain(engine_id: str, catalog: Dict[str, Any]) -> int:
    for eng in catalog["engines"]:
        if eng["id"] != engine_id:
            continue
        print("")
        print(eng["name"])
        print("=" * len(eng["name"]))
        print("")
        print(_wrap(eng["summary"]))
        for label, key in (
            ("Fits", "fits"),
            ("WRONG FOR", "wrong_for"),
            ("Edition and licensing traps", "edition_traps"),
            ("Operational notes", "operational_notes"),
        ):
            items = eng.get(key) or []
            if not items:
                continue
            print("")
            print(label)
            print("")
            for it in items:
                print(_wrap("- " + it))
                print("")
        print("Scale to zero: " + eng.get("scale_to_zero", "unknown"))
        print("Exit cost: " + eng.get("exit_cost", "unknown"))
        cites = eng.get("citations") or []
        if cites:
            print("")
            print("Sources (re-check before relying on one):")
            for c in cites:
                print("  - " + c["url"] + "  (read " + c["accessed"] + ")")
                print(_wrap(c["claim"], indent="      "))
        print("")
        return 0
    ids = ", ".join(e["id"] for e in catalog["engines"])
    print("Unknown engine '" + engine_id + "'. Known: " + ids)
    return 2


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Recommend a datastore, with reasoning.")
    p.add_argument("--answers", help="JSON file of answers (skips the interview)")
    p.add_argument("--output", "-o", help="Write the decision record here")
    p.add_argument("--json", action="store_true", help="Emit the raw recommendation as JSON")
    p.add_argument("--explain", metavar="ENGINE", help="Print one catalog entry and exit")
    args = p.parse_args(argv)

    catalog = load_catalog()

    if args.explain:
        return explain(args.explain, catalog)

    if args.answers:
        answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
    elif sys.stdin.isatty():
        answers = interactive(load_questions())
    else:
        print("No --answers file and no terminal to interview on.", file=sys.stderr)
        return 2

    rec = evaluate(answers, catalog)

    if args.json:
        print(json.dumps(rec.to_dict(), indent=2))
        return 0

    doc = render_markdown(rec, answers, catalog)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(doc, encoding="utf-8")
        print("Wrote " + str(out))
        if not rec.operationally_ready:
            print("Blocking verifications are outstanding — see the record.")
    else:
        print(doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
