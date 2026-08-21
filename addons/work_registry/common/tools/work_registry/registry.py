#!/usr/bin/env python3
"""work_registry — a shared noticeboard so concurrent agents can see each other.

WHAT THIS IS NOT
----------------
Not a lock. Not a lease. It has no fencing tokens and enforces nothing. If you need
real mutual exclusion with safe takeover, that already exists and is correct:
`addons/orchestrator_session/.../orchestrator_control.py` implements owner_claims with
lease_epoch + fencing_token + heartbeat + takeover. Do not reimplement that here.

WHY THIS EXISTS ANYWAY
----------------------
Two sessions edited the same build directory on the same machine. Neither had any way to
notice the other; the collision was found by reading git log and guessing. The
orchestrator's leases are coupled to its task lifecycle - you cannot claim a resource
without being a task in its model - which is correct for orchestrated work and too heavy
for "I am about to edit this directory for ten minutes."

So this is the cheap layer underneath: advisory, one file, stdlib only, no daemon.
Declare what you are touching. Look before you touch. That alone would have prevented
tonight.

USAGE
    registry.py claim <resource> --intent "what you are doing" [--ttl 3600]
    registry.py list [--all]
    registry.py check <resource>          # exit 1 if someone else holds it
    registry.py heartbeat <resource>
    registry.py release <resource>

Entries expire; a crashed agent stops blocking the noticeboard on its own.
"""
from __future__ import annotations

import argparse, hashlib, json, os, socket, sys, time
from datetime import datetime, timezone
from pathlib import Path

REGISTRY = Path(os.environ.get("WORK_REGISTRY",
                               Path.home() / ".firestarter" / "work-registry.json"))
DEFAULT_TTL = 3600


def _now() -> float: return time.time()
def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def _me() -> str:
    """Stable identity for the *agent*, not the process.

    This bit up front because testing caught it: an early version returned
    f"pid{os.getpid()}" and could not recognise its own claim on the next
    invocation, since claim/heartbeat/release run as separate processes. Identity
    has to survive across processes or the whole thing is useless to a build script.

    Order: explicit override, then whatever session id the harness exposes, then a
    per-terminal fallback, and only then a pid that will not survive - with a warning,
    because silently unstable identity is how this breaks quietly.
    """
    if os.environ.get("WORK_REGISTRY_OWNER"):
        return os.environ["WORK_REGISTRY_OWNER"]
    for k in ("CLAUDE_SESSION_ID", "CCD_SESSION_ID", "CODEX_SESSION_ID"):
        if os.environ.get(k):
            return f"{os.environ[k][:12]}@{socket.gethostname()}"
    # A terminal session shares TERM_SESSION_ID / windowid across processes.
    for k in ("TERM_SESSION_ID", "WINDOWID", "STY", "TMUX_PANE"):
        if os.environ.get(k):
            digest = hashlib.sha256(os.environ[k].encode()).hexdigest()[:8]
            return f"term-{digest}@{socket.gethostname()}"
    print("warning: no stable session id found; set WORK_REGISTRY_OWNER or this "
          "process will not recognise its own claim next invocation", file=sys.stderr)
    return f"pid{os.getpid()}@{socket.gethostname()}"


def _load() -> dict:
    if not REGISTRY.exists():
        return {"entries": {}}
    try:
        return json.loads(REGISTRY.read_text())
    except json.JSONDecodeError:
        # A torn file must not wedge every agent on the machine.
        return {"entries": {}}


def _save(data: dict) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY.with_suffix(f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    os.replace(tmp, REGISTRY)          # atomic; readers see whole file or old file


def _live(data: dict) -> dict:
    now = _now()
    return {k: v for k, v in data["entries"].items() if v.get("expires_at", 0) > now}


def cmd_claim(a) -> int:
    data = _load(); live = _live(data); me = _me()
    held = live.get(a.resource)
    if held and held["owner"] != me and not a.force:
        print(f"HELD by {held['owner']} since {_iso(held['acquired_at'])}", file=sys.stderr)
        print(f"  intent: {held['intent']}", file=sys.stderr)
        print(f"  expires: {_iso(held['expires_at'])}", file=sys.stderr)
        print("  --force to take it anyway (say why; they may be mid-write)", file=sys.stderr)
        return 1
    data["entries"] = live
    data["entries"][a.resource] = {
        "owner": me, "intent": a.intent,
        "acquired_at": held["acquired_at"] if held and held["owner"] == me else _now(),
        "heartbeat_at": _now(), "expires_at": _now() + a.ttl,
    }
    _save(data)
    print(f"claimed {a.resource} as {me}")
    return 0


def cmd_check(a) -> int:
    held = _live(_load()).get(a.resource)
    if not held:
        print(f"{a.resource}: free"); return 0
    mine = held["owner"] == _me()
    print(f"{a.resource}: held by {held['owner']}{' (you)' if mine else ''} — {held['intent']}")
    return 0 if mine else 1


def cmd_list(a) -> int:
    data = _load(); entries = data["entries"] if a.all else _live(data)
    if not entries:
        print("nothing claimed"); return 0
    now = _now()
    for res, e in sorted(entries.items()):
        state = "LIVE " if e.get("expires_at", 0) > now else "stale"
        age = int((now - e["acquired_at"]) / 60)
        print(f"  {state} {res}\n        {e['owner']}  {age}m  — {e['intent']}")
    return 0


def cmd_heartbeat(a) -> int:
    data = _load(); e = data["entries"].get(a.resource)
    if not e or e["owner"] != _me():
        print("not yours to renew", file=sys.stderr); return 1
    e["heartbeat_at"] = _now(); e["expires_at"] = _now() + a.ttl
    _save(data); print(f"renewed {a.resource}"); return 0


def cmd_release(a) -> int:
    data = _load(); e = data["entries"].get(a.resource)
    if not e: print("not claimed"); return 0
    if e["owner"] != _me() and not a.force:
        print(f"held by {e['owner']}, not you; --force to override", file=sys.stderr); return 1
    del data["entries"][a.resource]; _save(data); print(f"released {a.resource}"); return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("claim"); c.add_argument("resource")
    c.add_argument("--intent", required=True); c.add_argument("--ttl", type=int, default=DEFAULT_TTL)
    c.add_argument("--force", action="store_true"); c.set_defaults(fn=cmd_claim)
    k = sub.add_parser("check"); k.add_argument("resource"); k.set_defaults(fn=cmd_check)
    l = sub.add_parser("list"); l.add_argument("--all", action="store_true"); l.set_defaults(fn=cmd_list)
    h = sub.add_parser("heartbeat"); h.add_argument("resource")
    h.add_argument("--ttl", type=int, default=DEFAULT_TTL); h.set_defaults(fn=cmd_heartbeat)
    r = sub.add_parser("release"); r.add_argument("resource")
    r.add_argument("--force", action="store_true"); r.set_defaults(fn=cmd_release)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
