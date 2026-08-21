# Universal work-lease service — survey before building

**Status:** proposal. Nothing built yet, deliberately.
**Written:** 2026-08-21, after two sessions collided on the same build directory.

## Why this exists

Two Claude sessions edited `~/development/cervical-cord-video` at the same time. Both were doing good
work; one nearly deployed the other's half-finished state to a live share a collaborator reads. The
instinct was to add a lock to that repo. That instinct is how five projects end up with five
incompatible locks.

So: survey first, and record what already exists before writing anything.

## What already exists — do not rebuild these

### `orchestrator_session` — leases and queueing, already correct

`addons/orchestrator_session/common/orchestrator-control/orchestrator_control.py` (~6.6k lines,
Python stdlib only, SQLite-backed) already implements the hard part:

| Table / verb | What it gives you |
|---|---|
| `owner_claims.canonical_resource_key` | resource identity to claim against |
| `owner_claims.lease_epoch`, `fencing_token` | **fencing tokens** — the correct defence against a stale lease-holder writing after a takeover |
| `heartbeat_at`, `expires_at` | lease renewal and expiry |
| `takeover-lease`, `record-heartbeat` | CLI verbs for the full lease lifecycle |
| `tasks`, `runnable_queue_count`, `queue_entered_at`, `queue_seconds` | a real work queue with priority and blocking states |
| `capacity-watchdog`, `lifecycle-watchdog`, `recycle-queue` | reaping and requeue |

**Fencing tokens are the part people get wrong.** A lease that only has an expiry is unsafe: a holder
that stalls past expiry and then wakes up will happily write over the new holder. A monotonic fencing
token lets the resource reject the stale writer. This is already here and it should not be
reimplemented anywhere else.

### `adaptive_capacity_policy.py` — advisory only, and says so

Same addon. Its docstring is explicit: *"no host collector, persistence layer, task dispatcher,
admission hook, or service-control dependency… The result is never an authorization or reservation
receipt."* It answers "how loaded are we"; it deliberately does not answer "may I run". Don't mistake
it for an admission controller.

### `service_supervisor` — catalog, lifecycle and permits

Owns the allowlist, lifecycle contract and PM execution-permit verification for local services. A
hosted work-lease service should register here rather than inventing its own supervision.

## What is actually missing

The logic is done. The **service** is not.

1. **No network surface.** `orchestrator_control.py` calls itself *"local-only"*. It is a CLI over a
   local SQLite file, so it cannot arbitrate between processes on different machines — or reliably
   between containers.
2. **No container.** No Dockerfile, no compose entry.
3. **Nobody outside the orchestrator uses it.** `cervical-cord-video` has no lock at all — it did not
   reinvent leasing, it simply has none. Same likely true of the other build directories.
4. **No client shim.** Adoption needs something a build script can call in one line, or it will not
   be adopted.

## Proposal

**Do not write a new lease implementation.** Wrap the existing one.

1. **Thin HTTP surface** over `orchestrator_control.py` — `claim`, `heartbeat`, `release`, `takeover`,
   `status`. No new semantics; the SQLite control plane stays the source of truth.
2. **Dockerise it** and run it from firestarter, registered with `service_supervisor`.
3. **A one-line client shim** so a build script can wrap itself in a lease without importing 6.6k
   lines. This is the adoption lever — without it, projects keep having no lock.
4. **Local first, hosted later.** SQLite on a single host is fine for one laptop. Moving to a shared
   or cloud deployment means swapping the store for something with real concurrent writes — that is a
   later decision and should not block step 1.

## The rule this came from

When a project needs infrastructure, search the other projects before writing it. The clever part is
usually already solved somewhere, done better than a fresh attempt under time pressure — the fencing
tokens above being the case in point. What is usually missing is not the logic but the *packaging*
that would let anyone else use it.
