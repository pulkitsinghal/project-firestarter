#!/usr/bin/env python3
"""Additive, commutative, fenced deploys — so concurrent agents stop blocking each other.

THE FAILURE THIS REMOVES
------------------------
Most static deploys mirror a directory: `wrangler pages deploy`, `aws s3 sync --delete`,
`netlify deploy --prod`, `rsync --delete`, `gh-pages`. Anything the live site has and
your directory lacks is DELETED. That is fine with one deployer and catastrophic with
several, because each agent typically holds only the artefact it is working on. Two
agents then take turns removing each other's work, and the person holding the link gets
a 404 with no warning.

The instinctive fix — a lock, or refusing to deploy when something is missing — trades
data loss for blocking. That is the same problem wearing a better hat: the whole point
is that peers should not have to wait for each other.

THREE PROPERTIES, IN THE ORDER THEY MATTER
------------------------------------------
**Additive.** The live site publishes its own manifest (`_deployed.json`). Before
deploying, read it, union it with yours, and restore anything you are missing by
downloading the files the manifest lists. A deploy then carries everyone's artefacts,
not just the ones this agent happens to have on disk.

**Commutative.** The union is by id and never drops an entry; a genuine conflict on the
same id is settled by the newer timestamp. Two agents publishing different artefacts
converge to the same state regardless of who goes last — which is what removes the need
to coordinate at all. This is the CRDT idea applied to a deploy: make the merge
order-independent and the race stops mattering.

**Fenced.** The one genuinely global resource is the live site, so let it hold the
register. `_deploy-state.json` carries a monotonically increasing token; read the live
token, publish `live + 1`, then verify yours is what landed. An agent that prepared its
deploy against an older view of the world finds out, and re-reconciles instead of
overwriting. This is a fencing token in the Kleppmann sense — the register that decides
is the resource itself, not a lock held beside it.

WHAT THIS IS NOT
----------------
Not a lease, and not a lock. The `work_registry` add-on is an advisory noticeboard, and
`orchestrator_session` has real leases with heartbeats and takeover. Both are about
*discovery* — knowing a peer exists. This module assumes discovery failed, or was
ignored, or the peer is on another machine entirely, and makes the outcome correct
anyway. Use them together: the registry to avoid surprising each other, this to be safe
when you do.

ADOPTING IT
-----------
Provide a `files` list per entry when you stage an artefact (`file_list()` does this),
point `BASE_URL` at the live site, and call `merge_manifests` → `heal` → `next_token` →
`write_state` before your upload command, `verify_not_superseded` after it. See
docs/CONVERGENT_DEPLOY.md.
"""
from __future__ import annotations

import json
import os
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

STATE_FILE = "_deploy-state.json"
MANIFEST_FILE = "_deployed.json"

# Vocabulary. A project that already has its own manifest shape rebinds these once at
# import rather than threading them through every call.
COLLECTION = "entries"   # the list key inside the manifest
ID = "id"                # the field that identifies an entry
STAMP = "added"          # ISO-8601; newer wins a same-id conflict
SUBDIR = ""              # path under the deploy root, e.g. "s" for /s/<id>/
UA = {"User-Agent": "Mozilla/5.0 (convergent-deploy)"}
ACCESS_CLIENT_ID_ENV = "CF_ACCESS_CLIENT_ID"
ACCESS_CLIENT_SECRET_ENV = "CF_ACCESS_CLIENT_SECRET"


class Unreadable(RuntimeError):
    """Live state may exist, but it could not be read safely.

    This is deliberately distinct from a 404. Treating blindness as absence lets a
    deploy reset the fence and erase peer artefacts while reporting success.
    """


def _safe_url(url: str) -> str:
    """Name a URL in an error without leaking query credentials or fragments."""
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _access_headers() -> dict[str, str]:
    """Return Cloudflare Access service-token headers when configured.

    Human reviewers may enter through an email OTP, but unattended reconciliation
    needs a machine credential. The upload API token is not that credential. Never
    send half a service token: it is neither anonymous nor authenticated and produces
    a misleading access-gate failure.
    """
    client_id = os.environ.get(ACCESS_CLIENT_ID_ENV, "").strip()
    client_secret = os.environ.get(ACCESS_CLIENT_SECRET_ENV, "").strip()
    if bool(client_id) != bool(client_secret):
        raise Unreadable(
            f"set both {ACCESS_CLIENT_ID_ENV} and {ACCESS_CLIENT_SECRET_ENV}, or neither"
        )
    if not client_id:
        return {}
    return {
        "CF-Access-Client-Id": client_id,
        "CF-Access-Client-Secret": client_secret,
    }


def _fetch_json(base: str, name: str):
    """Read a live JSON object; only a genuine 404 means "not published yet"."""
    url = f"{base.rstrip('/')}/{name}"
    try:
        req = urllib.request.Request(url, headers={**UA, **_access_headers()})
        with urllib.request.urlopen(req, timeout=60) as r:
            final_url = r.geturl()
            if final_url != url:
                raise Unreadable(
                    f"{_safe_url(url)} redirected to {_safe_url(final_url)}; "
                    "the live state may be behind an access gate"
                )
            try:
                payload = json.loads(r.read().decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise Unreadable(
                    f"{_safe_url(url)} did not return a JSON object; "
                    "an access/WAF interstitial may have answered instead"
                ) from exc
            if not isinstance(payload, dict):
                raise Unreadable(f"{_safe_url(url)} returned JSON, but not an object")
            return payload
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise Unreadable(f"{_safe_url(url)} returned HTTP {exc.code}") from exc
    except Unreadable:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise Unreadable(f"{_safe_url(url)} is unreachable: {exc}") from exc


def _fetch_file(url: str, dest: pathlib.Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={**UA, **_access_headers()})
        with urllib.request.urlopen(req, timeout=600) as r:
            if r.status != 200 or r.geturl() != url:
                return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as fh:
                while chunk := r.read(1 << 20):
                    fh.write(chunk)
        return True
    except Unreadable:
        raise
    except Exception:
        return False


def file_list(entry_dir: pathlib.Path) -> list[str]:
    """Relative paths of everything in a staged artefact, so a peer can restore it."""
    return sorted(str(f.relative_to(entry_dir)) for f in entry_dir.rglob("*") if f.is_file())


def _safe_manifest_path(value: str, *, field: str, nested: bool) -> pathlib.PurePosixPath:
    """Validate a remote manifest path before using it as a URL or filesystem path."""
    if not isinstance(value, str) or not value or "\\" in value:
        raise Unreadable(f"remote manifest has an unsafe {field}")
    path = pathlib.PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise Unreadable(f"remote manifest has an unsafe {field}")
    if not nested and len(path.parts) != 1:
        raise Unreadable(f"remote manifest has an unsafe {field}")
    return path


def merge_manifests(local: dict, remote: dict | None) -> tuple[dict, list[str]]:
    """Union by slug. Never drops an entry; newer `added` wins a genuine conflict.

    This is the commutative part: whichever session deploys last, the result is the
    same, so neither has to wait for the other.
    """
    by_id = {e[ID]: e for e in (remote or {}).get(COLLECTION, [])}
    mine = {e[ID] for e in local.get(COLLECTION, [])}
    for entry in local.get(COLLECTION, []):
        prev = by_id.get(entry[ID])
        if prev is None or entry.get(STAMP, "") >= prev.get(STAMP, ""):
            by_id[entry[ID]] = entry
    adopted = sorted(k for k in by_id if k not in mine)
    merged = {COLLECTION: sorted(by_id.values(), key=lambda e: e.get(STAMP, ""))}
    return merged, adopted


def heal(root: pathlib.Path, merged: dict, base_url: str,
         backups: pathlib.Path) -> tuple[list[str], list[str]]:
    """Restore entries this agent does not hold, so the deploy stays additive.

    Two sources, **most current first**: the live site itself, using the file list the
    manifest carries, and only then a local backup.

    The order is the whole point, and I had it backwards. Preferring the cheap local
    backup meant a fresh clone — whose `.backups/` are whatever was committed, possibly
    months old — would restore a stale build and publish it over the current one. That
    is the same clobber this module exists to prevent, arriving by a politer route. A
    backup restore is therefore a fallback for when the live site cannot be reached, and
    it says STALE in its report so nobody mistakes it for a clean recovery.

    A slug we cannot restore is reported rather than silently dropped — deploying
    without it would delete it for whoever holds the link.
    """
    healed, unhealable = [], []
    for entry in merged[COLLECTION]:
        slug = entry[ID]
        safe_slug = _safe_manifest_path(slug, field=ID, nested=False)
        dest = (root / SUBDIR / safe_slug) if SUBDIR else (root / safe_slug)
        if dest.exists():
            continue
        files = entry.get("files") or []
        safe_files = [_safe_manifest_path(f, field="file path", nested=True) for f in files]
        prefix = f"{SUBDIR.strip('/')}/" if SUBDIR else ""
        if safe_files and all(
            _fetch_file(
                f"{base_url.rstrip('/')}/{prefix}"
                f"{urllib.parse.quote(str(safe_slug), safe='')}/"
                f"{urllib.parse.quote(str(f), safe='/')}",
                dest.joinpath(*f.parts),
            )
            for f in safe_files
        ):
            healed.append(f"{slug} (from live site, {len(files)} files)")
            continue
        if dest.exists():
            import shutil
            shutil.rmtree(dest)          # a half-downloaded share is worse than none
        bak = sorted(backups.glob(f"*{safe_slug}*"), reverse=True) if backups.exists() else []
        if bak and any(bak[0].rglob("index.html")):
            import shutil
            shutil.copytree(bak[0], dest, dirs_exist_ok=True)
            healed.append(f"{slug} (STALE: from backup {bak[0].name}; live site was "
                          f"unreachable, so this may be an older build)")
            continue
        unhealable.append(f"{slug} (live unreachable and no usable backup)"
                          if files else
                          f"{slug} (no file list recorded; cannot restore)")
    return healed, unhealable


def next_token(base_url: str, local_token: int = 0) -> int:
    """One past whatever the live site says. The resource is its own register."""
    state = _fetch_json(base_url, STATE_FILE) or {}
    return max(int(state.get("token", 0)), int(local_token)) + 1


def write_state(root: pathlib.Path, merged: dict, token: int, owner: str) -> None:
    (root / STATE_FILE).write_text(json.dumps(
        {"token": token, "owner": owner, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
        indent=2) + "\n")
    (root / MANIFEST_FILE).write_text(json.dumps(merged, indent=2) + "\n")


def verify_not_superseded(base_url: str, token: int) -> str | None:
    """After deploying, confirm the token we published is the one that landed.

    If another session deployed between our reconcile and our upload, the live token
    will not be ours. That is recoverable — re-run — and it is far better to say so
    than to assume our view won.
    """
    state = _fetch_json(base_url, STATE_FILE) or {}
    live = int(state.get("token", -1))
    if live == token:
        return None
    return (f"live token is {live}, we published {token} — another deploy landed "
            f"concurrently. Re-run deploy; reconciliation will pick up their shares.")
