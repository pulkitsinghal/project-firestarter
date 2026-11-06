# {{ project_name }} safety model

One page for the whole-system view the per-control docs (`SECURITY.md`,
`COMPLIANCE_POSTURE.md`, `DEPLOY_POLICY.md`, `ROLLBACK.md`, and the executable
guards) each leave out: how the controls behave **together**. Read it before you
add or change a control, and keep it current.

"Each control is correct on its own" and "the controls cohere when they are all
enabled" are different claims, and only the second one survives composition. A
control that is individually right can silently defeat another that is also
individually right, and that failure is invisible to any doc that looks at one
control at a time. This file is where it gets written down before it bites.

## Two things to state for every control

1. **Resting state.** Is it default ON or default OFF? With its flag absent,
   does it intercept nothing (every consumer takes the default path), or is it
   always in the path? Name the state that is safe when nobody has configured
   anything.
2. **Failure direction.** Which way does it fail *safe*? **"Fail closed" is not a
   universal answer.** On a metered or life-safety path the safe failure is often
   *pass through untouched* — "don't intercept" — not "deny", because denying is
   itself the harm. Choose the direction per control; do not let one default
   propagate across all of them.

Then state the **interaction**: when two controls are enabled at once, does one
defeat the other? Say it rather than assume it.

## Layers

The protective controls this project actually runs. Keep it to the ones really
enabled; add a row when you add a control.

_No layers recorded yet for this project._

## Resting state and failure direction (per layer)

For each layer above: its resting state, the direction it fails safe, and the
reason that direction is the safe one here.

_No layers recorded yet._

## Known interaction gaps (dated, verified)

Where the "safe together" claim is known to fail — recorded concretely, naming
the two controls whose interaction produced it, with the date it was last
verified. An undated or unverified gap is worse than none, because it is believed
without being checked; this pairs with the "an empirical invariant carries a
verified-on date" precept in `AGENTS.md`.

_No interaction gaps recorded yet. Replace this line when the first one is
verified; do not import another project's gaps as though this project found
them._

## Worked example (synthetic, illustrative, not this project)

A system with three independent layers, to show the shape — invented, not a
claim about this repository:

- **Layer 1, intercept gate (resting state: default OFF).** With its flag absent
  it intercepts nothing and every consumer uses the default path. Default OFF is
  the safe resting state because an unconfigured deploy is a normal deploy, not a
  broken one.
- **Layer 2, routing policy (two invariants, stated as directions).**
  Life-safety traffic must **never fall back** to the untrusted path; metered
  traffic must **never black-hole** — an unmatched flow must pass through
  untouched, because on that path "deny" is the harm, not the safeguard.
- **Layer 3, failover actor (acts only when the alternative is confirmed
  working).** It promotes a replacement only after proving the replacement
  serves; it never fails away from a working primary toward an unverified one.

Each layer is safe on its own; together they are meant to guarantee that a
running system cannot quietly strand its dependents.

**Gap (illustrative, synthetic date 2026-01-01).** Layer 1's enforcing component
reads its config once at startup and no-ops the `reload` command, so a live
policy change from Layer 2 never reaches a process that started before the
change. Every layer behaves correctly in isolation, yet Layer 2's "never fall
back" invariant is silently violated. This is exactly the kind of entry the gap
register above exists to hold: concrete, dated, and naming the two controls
whose interaction produced it.
