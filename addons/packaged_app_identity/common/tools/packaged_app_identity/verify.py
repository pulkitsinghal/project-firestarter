#!/usr/bin/env python3
"""packaged_app_identity — prove a packaged desktop app is the build you think it is.

WHY THIS EXISTS
---------------
Two macOS packaging failures masquerade as application-level connector bugs, and
both sail through every "does the feature work from my dev shell?" check:

  1. UI automation works when launched from a development shell but silently
     no-ops from the signed bundle, because the packaged app lacks the Apple
     Events automation entitlement or its Info.plist usage description.
  2. Local builds share one bundle identifier and single-instance lock while
     using versioned bundle names. Replacing the bundle on disk can leave the
     prior executable running; opening the new path reactivates the stale
     process, so the *visible* build is not the *installed* build.

This tool is the reusable, source-safe set of checks for those failures. It is
deterministic, stdlib-only, and OBSERVE / PLAN ONLY: it reads inputs and prints
a verdict or a plan. It never launches, signals, installs, or terminates
anything. The one genuinely host-only step — extracting entitlements from a
signed bundle with `codesign` — lives in the sibling `acceptance.sh`, which
feeds this tool and skips cleanly off macOS.

CONTENT SUPPRESSION (the same discipline as scripts/verify-live.sh)
-------------------------------------------------------------------
A packaged Info.plist, an entitlements plist, and a process path can each carry
user-identifying detail. This tool reports verdicts by *key name*, *basename*,
and *match / mismatch* — never by dumping a plist, a full absolute path, or a
process command line. Build identities are opaque, non-sensitive markers by
contract (a version plus short commit, or a build uuid), so they may be echoed.

EXIT CODES
----------
  0  the checked contract holds
  1  the contract is violated (the negative case fired)
  2  usage / malformed or unreadable input
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import sys
from pathlib import PurePosixPath


APPLE_EVENTS_ENTITLEMENT = "com.apple.security.automation.apple-events"
APPLE_EVENTS_USAGE_KEY = "NSAppleEventsUsageDescription"


def _load_plist(path: str):
    """Read an XML or binary property list. Returns a dict, or None after
    reporting a bounded error (never echoes the file's contents or its path)."""
    try:
        with open(path, "rb") as handle:
            data = plistlib.load(handle)
    except FileNotFoundError:
        print("error: property list not found at the given path", file=sys.stderr)
        return None
    except (OSError, ValueError, plistlib.InvalidFileException):
        print("error: property list is unreadable or malformed", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print("error: property list root is not a dictionary", file=sys.stderr)
        return None
    return data


def _inside(child: str, parent: str) -> bool:
    """Pure path containment: is `child` at or below `parent`? Normalizes
    `.`/`..` lexically but never touches the filesystem or resolves symlinks,
    so it is correct for describing a bundle on another machine."""
    child_parts = PurePosixPath(os.path.normpath(child)).parts
    parent_parts = PurePosixPath(os.path.normpath(parent)).parts
    return (
        len(child_parts) >= len(parent_parts)
        and child_parts[: len(parent_parts)] == parent_parts
    )


def cmd_entitlement(args) -> int:
    data = _load_plist(args.entitlements)
    if data is None:
        return 2
    value = data.get(args.key)
    if value is True:
        print(f"PASS entitlement present and enabled: {args.key}")
        return 0
    if args.key not in data:
        print(f"FAIL entitlement absent: {args.key}", file=sys.stderr)
    else:
        print(
            f"FAIL entitlement present but not enabled (value is not true): {args.key}",
            file=sys.stderr,
        )
    return 1


def cmd_usage_description(args) -> int:
    data = _load_plist(args.info_plist)
    if data is None:
        return 2
    value = data.get(args.key)
    if isinstance(value, str) and value.strip():
        print(f"PASS usage description present and non-empty: {args.key}")
        return 0
    if args.key not in data:
        print(f"FAIL usage description absent: {args.key}", file=sys.stderr)
    elif not isinstance(value, str):
        print(f"FAIL usage description is not a string: {args.key}", file=sys.stderr)
    else:
        print(f"FAIL usage description is present but empty: {args.key}", file=sys.stderr)
    return 1


def cmd_identity(args) -> int:
    running_id = (args.running_identity or "").strip()
    bundle_id = (args.bundle_identity or "").strip()
    if not running_id or not bundle_id:
        print(
            "error: --running-identity and --bundle-identity must be non-empty",
            file=sys.stderr,
        )
        return 2

    problems = []
    if not _inside(args.running_exec, args.bundle):
        problems.append(
            "running executable is outside the installed bundle "
            f"(running={os.path.basename(os.path.normpath(args.running_exec))}, "
            f"bundle={os.path.basename(os.path.normpath(args.bundle))})"
        )
    if running_id != bundle_id:
        problems.append(
            "running build identity does not match the installed bundle "
            f"(running={running_id}, installed={bundle_id})"
        )

    if problems:
        for problem in problems:
            print(f"FAIL {problem}", file=sys.stderr)
        print(
            "the visible process is not the build you just installed; stop the "
            "exact prior pid and relaunch the installed bundle",
            file=sys.stderr,
        )
        return 1
    print(f"PASS running process matches the installed build (identity={running_id})")
    return 0


def cmd_lock_check(args) -> int:
    owner = (args.owner_identity or "").strip()
    expected = (args.expected_identity or "").strip()
    if not owner or not expected:
        print(
            "error: --owner-identity and --expected-identity must be non-empty",
            file=sys.stderr,
        )
        return 2
    if owner == expected:
        print(f"PASS single-instance lock held by the current build (identity={owner})")
        return 0
    pid_note = f" (owner pid {args.owner_pid})" if args.owner_pid else ""
    print(
        f"FAIL a stale process owns the single-instance lock{pid_note}: owner "
        f"build identity {owner} != expected {expected}",
        file=sys.stderr,
    )
    print(
        "fail installation/launch visibly; do not let the stale instance keep the lock",
        file=sys.stderr,
    )
    return 1


def cmd_stop_plan(args) -> int:
    if args.pid <= 0:
        print("error: --pid must be a positive integer", file=sys.stderr)
        return 2
    plan = {
        "target_pid": args.pid,
        "non_executing": True,
        "steps": [
            {
                "action": "verify-owner",
                "pid": args.pid,
                "note": "confirm this exact pid is the prior app instance before signalling",
            },
            {"action": "signal", "signal": "TERM", "pid": args.pid},
            {"action": "wait", "seconds": args.grace, "pid": args.pid},
            {"action": "signal-if-still-running", "signal": "KILL", "pid": args.pid},
            {"action": "verify-stopped", "pid": args.pid},
        ],
        # The rule this planner exists to enforce: it can only ever name one pid.
        "forbidden": (
            "never terminate by process name or pattern (killall / pkill -f / "
            "kill by comm); exact pid only"
        ),
    }
    print(json.dumps(plan, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    entitlement = sub.add_parser(
        "entitlement",
        help="assert a signed app's extracted entitlements carry a required key",
    )
    entitlement.add_argument(
        "--entitlements",
        required=True,
        help="path to an entitlements plist extracted from the signed app",
    )
    entitlement.add_argument("--key", default=APPLE_EVENTS_ENTITLEMENT)
    entitlement.set_defaults(fn=cmd_entitlement)

    usage = sub.add_parser(
        "usage-description",
        help="assert the packaged Info.plist carries a non-empty usage description",
    )
    usage.add_argument("--info-plist", required=True, dest="info_plist")
    usage.add_argument("--key", default=APPLE_EVENTS_USAGE_KEY)
    usage.set_defaults(fn=cmd_usage_description)

    identity = sub.add_parser(
        "identity",
        help="assert the running process is the build you just installed",
    )
    identity.add_argument("--running-exec", required=True, dest="running_exec")
    identity.add_argument("--bundle", required=True)
    identity.add_argument("--running-identity", required=True, dest="running_identity")
    identity.add_argument("--bundle-identity", required=True, dest="bundle_identity")
    identity.set_defaults(fn=cmd_identity)

    lock = sub.add_parser(
        "lock-check",
        help="fail visibly when a stale build owns the single-instance lock",
    )
    lock.add_argument("--owner-identity", required=True, dest="owner_identity")
    lock.add_argument("--expected-identity", required=True, dest="expected_identity")
    lock.add_argument("--owner-pid", dest="owner_pid", default="")
    lock.set_defaults(fn=cmd_lock_check)

    stop = sub.add_parser(
        "stop-plan",
        help="print a non-executing graceful-stop plan for exactly one pid",
    )
    stop.add_argument("--pid", required=True, type=int)
    stop.add_argument("--grace", type=int, default=10)
    stop.set_defaults(fn=cmd_stop_plan)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
