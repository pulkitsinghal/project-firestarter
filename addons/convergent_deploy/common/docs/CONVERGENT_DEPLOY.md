# Deploying without blocking your peers

If more than one agent (or person, or CI job) can publish to this site, read this before
writing a deploy command.

## Why the obvious deploy is unsafe

`wrangler pages deploy ./site`, `aws s3 sync ./site s3://bucket --delete`, `rsync -a
--delete`, `netlify deploy --prod` — all of them **mirror**. Anything live that is absent
from your directory is deleted.

With one deployer that is a feature. With several it is a live-fire hazard, because each
agent usually holds only the artefact it is working on. Agent A deploys and removes B's
pages; B deploys and removes A's. Nobody sees an error. The failure surfaces days later
as a 404 in someone else's inbox.

The tempting fixes are both wrong:

- **A lock.** Now your peers wait on you, which is the cost we were trying to avoid — and
  a lock held by a crashed agent is worse than no lock.
- **Refuse to deploy when something is missing.** This is what we tried first. It turns
  silent data loss into loud blocking. Better, still bad: an agent with a correct
  artefact cannot ship it because of an unrelated gap.

## What we do instead

`scripts/converge.py`, three properties:

**Additive.** The site publishes its own manifest at `_deployed.json`, and each entry
records the files it consists of. Before uploading, we download anything the manifest
lists that we do not hold. A deploy therefore carries everyone's artefacts.

**Commutative.** The merge is a union by id that never drops an entry; a same-id conflict
is settled by the newer timestamp. Two agents converge to the same state regardless of
who deploys last — the race stops mattering rather than being prevented.

**Fenced.** `_deploy-state.json` holds a monotonically increasing token. We read the live
token, publish `live + 1`, upload, then check that ours is the one that landed. An agent
that prepared against a stale view finds out and re-runs. The register that decides is
the resource itself, not a lock beside it — a fencing token in Kleppmann's sense.

## Wiring it in

```python
import converge

owner  = os.environ.get("WORK_REGISTRY_OWNER", "unknown-session")
local  = json.loads(MANIFEST.read_text())
remote = converge._fetch_json(BASE_URL, converge.MANIFEST_FILE)

merged, adopted = converge.merge_manifests(local, remote)
healed, unhealable = converge.heal(SITE_ROOT, merged, BASE_URL, BACKUPS)
if unhealable:
    sys.exit(f"cannot safely deploy; would delete: {unhealable}")

token = converge.next_token(BASE_URL)
converge.write_state(SITE_ROOT, merged, token, owner)

run_your_upload_command()

if msg := converge.verify_not_superseded(BASE_URL, token):
    sys.exit(msg)          # someone landed between our read and our write; re-run
```

If your manifest already has its own shape, rebind the vocabulary once at import:

```python
converge.COLLECTION, converge.ID, converge.STAMP, converge.SUBDIR = "shares", "slug", "added", "s"
```

## Two rules learned the hard way

**Unreadable is not absent.** A genuine 404 is normal before the first deploy. A
redirect, login/WAF page, timeout, malformed JSON or server error means the safety
mechanism is blind, so reconciliation stops. Never catch `converge.Unreadable` and
continue with an empty manifest: that resets the fence and can delete every peer's
artefact while reporting success.

If the site is protected by Cloudflare Access, human reviewers can use an approved
identity policy while unattended reconciliation uses a separate service token. Put
both halves in the runtime environment as `CF_ACCESS_CLIENT_ID` and
`CF_ACCESS_CLIENT_SECRET`; never commit them. The upload API token is a different
credential and cannot read through Access. Protect the provider origin too—an
anonymous alternate origin defeats the access policy.

**The live site beats a local backup.** Backups often get committed, so a fresh clone
carries whatever was backed up whenever it was committed. Restoring from one republished
a 47 KB page over the current 105 KB build — the same clobber this module exists to
prevent, arriving by a politer route. Currency is the ordering criterion, not cheapness.
A backup restore is the fallback for an unreachable site, and it reports itself as STALE.

**Tell every future session the entry point.** None of this helps if an agent runs the
raw mirror command, which is usually sitting right there in a docstring. Put the rule in
`CLAUDE.md`/`AGENTS.md` at the repo root — that is the layer that actually reaches a
session that has never seen this code:

> **Deploy only with `./deploy.py`. Never call `<mirror command>` directly.** It deletes
> anything live that is absent locally, and the artefacts are gitignored, so a fresh
> clone lacks all of them.
