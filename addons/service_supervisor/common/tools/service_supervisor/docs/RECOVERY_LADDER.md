# The recovery ladder: registration is not readiness

A supervisor's hardest case is not a dependency that is down. It is a dependency
that is **present, enumerated, link-up — and not working**. Every signal the
platform exposes says healthy; the thing is dead. The originating failure was a
cellular dongle whose interface was up but had no internet: the OS kept routing
through it because it demotes a service only on link-down, not on loss of
internet, and the whole machine was black-holed until the dongle was physically
unplugged.

This is one more rung of a ladder firestarter has climbed all year — a check
that did not run is not green; unreadable is not absent; a transport success is
not a valid payload; queued is not accepted. Each says a **status label
overstates reality.** This one says: **registration is not readiness.** A service
in the catalog, a container `Up`, a pod `Running`, a connection in the pool, a
name that resolves — none of those is evidence it serves.

This module is **observe-only**. It owns the catalog, the dependency graph and
the lifecycle state, and it does not act. `plan_recovery` is a pure planner: it
reasons over a synthetic observation and returns a non-executing plan, exactly
like `plan_wake` and `plan_idle`. It never reboots a device, never demotes a
route, never touches host state. Execution belongs to a platform-specific actor
outside this package, and the scope stops at the policy and the evidence
requirements — not any platform command.

## The ladder, in order

1. **Probe the real capability, not the registration.** The catalog declares a
   `recovery.liveness` probe that is *distinct* from `health`. `health` answers
   "is it registered and link-up"; `liveness` answers "does it actually serve".
   The planner records the probe it relied on so the whole decision path is
   auditable.
2. **Attempt a bounded in-place revive before failing over.** If `recovery.revive`
   is enabled, try to reboot the wedged dependency in place — no replacement —
   bounded by `max_attempts` and a `cooldown_ms`. A revive that keeps failing is
   not a revive: once attempts are exhausted or the cooldown is active, the rung
   is **blocked, not retried.** It must not loop.
3. **Fail over only to a confirmed-working alternative.** If `recovery.failover`
   is enabled *and* the alternative's own liveness is confirmed `serving`, demote
   the primary to it. If the alternative is `unknown` or `unreachable`, the
   failover is **refused** — failing over to an untested alternative converts one
   outage into two.
4. **Retest and come back.** Demotion is never permanent. The planner schedules a
   retest on `retest_interval_ms`; once the primary is confirmed serving again,
   it is re-promoted in place. A false alarm just leaves you on the alternative
   and self-heals on the next retest. While you are **already** serving from the
   alternative and the primary is still not serving, the planner *holds* on the
   alternative and keeps retesting — it does not fail over again (you are already
   there) and never annotates `stay-on-primary`. If the alternative itself stops
   serving, it holds **degraded** rather than failing back to a dead primary.

A fifth distinction runs underneath all of them: **enumerated-but-unreachable is
not dead-plugged.** A dependency that is `absent` has nothing present to revive
in place; only a confirmed failover can help it. Treating the two alike makes one
of them unrecoverable, so the planner diagnoses them separately
(`enumerated-unreachable` versus `absent`).

## Fail direction at each rung

Fail-closed is not the universal answer; each rung states where it goes when its
own attempt fails.

| Rung | On failure |
|------|------------|
| Probe liveness | Trust the probe, never the registration. Enumeration never upgrades to "serving". |
| Revive in place | Re-probe, then proceed to failover — never loop the revive. |
| Revive blocked (exhausted / cooling) | Proceed to the failover rung; do not keep trying in place. |
| Failover to confirmed alternative | Stay on the primary if the alternative is not confirmed serving (refuse). |
| No confirmed failover available | Hold in place, degraded, and keep probing. |
| Already failed over, primary still down | Hold on the alternative and retest; never re-fail-over, never fail back to the dead primary. |
| Failed over, alternative now down too | Hold degraded; do not fail back to the dead primary. |
| Retest | Stay on the alternative until the primary is genuinely healthy again. |

## Default-inert, and dry-run first

- A service with **no `recovery` block** has no ladder. Declaring a block is
  observe-only: the probe is declared, and the `revive` and `failover` actions
  stay **off** until each one's own `enabled` flag is set.
- Even when armed, this module only *plans*. **Every** step carries an explicit
  `armed` flag, so no future executor can ever see a missing key and default it to
  "execute". Run the plan with `dry_run: true` first: every step comes back
  `armed: false` and the plan's `mode` is `dry-run`. Outside dry-run, only a
  lifecycle-mutating rung (revive, failover, schedule-retest) is `armed: true`; a
  probe, hold, refusal, or block is always `armed: false`. A human can read the
  daemon's judgement before any actor is trusted to execute it.

```bash
python -m tools.service_supervisor plan-recovery \
  --manifest tools/service_supervisor/services.example.json \
  --service synthetic-api \
  --observation tools/service_supervisor/recovery-observation.example.json
```

The observation is a synthetic snapshot (`presence`, `liveness`,
`alternative_liveness`, `attempts_made`, `cooldown_active`, `failed_over`,
`retest_due`, `dry_run`); the command prints the ladder as JSON and changes
nothing. See [`service-catalog.schema.json`](../service-catalog.schema.json) for
the exact declared shape.
