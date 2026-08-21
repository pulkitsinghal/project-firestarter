# `work_registry` add-on (contributor notes)

> Documents the add-on for **firestarter maintainers**. Lives above `common/`, so the
> generator does not stamp it into projects. User-facing docs are
> `common/docs/WORK_REGISTRY.md`, which does stamp into `<project>/docs/`.

## What it is

A shared, advisory noticeboard so concurrent agents on one machine can see what each
other is touching. One JSON file, stdlib only, no daemon, no server.

## What it is deliberately NOT

**Not a lock, not a lease.** No fencing tokens, enforces nothing, `--force` always wins.

Real mutual exclusion already exists in this repo and is correct:
`addons/orchestrator_session/common/orchestrator-control/orchestrator_control.py` implements
`owner_claims` with `lease_epoch` + `fencing_token` + heartbeat + expiry + `takeover-lease`.
Fencing tokens are the part people get wrong — a lease with only an expiry lets a stalled
holder wake up and overwrite its successor — and that is solved there. **Do not
reimplement it here or anywhere else.**

## Why it exists anyway

Two agent sessions edited the same build directory on the same machine on 2026-08-20. Both
were doing good work; one nearly deployed the other's half-finished state to a live page a
collaborator reads. The collision was found by reading `git log` and guessing.

The orchestrator's leases are coupled to its task lifecycle — you cannot claim a resource
without being a task in its model, and the verbs take structured JSON requests. That is
right for orchestrated work and far too heavy for *"I am about to edit this directory for
ten minutes."* The gap was never mutual exclusion. It was **discovery**: nothing let one
agent notice another was already there.

So this is the cheap layer underneath. Declare what you are touching; look before you
touch. That alone would have prevented the incident.

## Design notes worth keeping

- **Atomic writes.** Temp file plus `os.replace`. A torn registry must never wedge every
  agent on the machine; a corrupt file is also treated as empty rather than fatal.
- **Identity must survive across processes.** An early version keyed on `os.getpid()` and
  could not recognise its own claim on the next invocation, because `claim`, `heartbeat`
  and `release` run as separate processes. Resolution order is `WORK_REGISTRY_OWNER`, then
  a harness session id, then a terminal-session hash, then pid **with a warning** —
  silently unstable identity is how this would have failed quietly.
- **Entries expire.** A crashed agent stops blocking the board without intervention.
- **Advisory on purpose.** It returns exit codes and prints who holds what; it never
  prevents anyone from proceeding. An agent that ignores it is not defeated by it — which
  is the honest contract, since nothing here can actually stop a write.

## Migration path

If enforcement is ever genuinely needed, do not grow this into a lock. Adopt
`orchestrator_session`'s lease model, which already has the semantics. The registry's
`resource` string is intentionally shaped like `canonical_resource_key` so entries map
across.
