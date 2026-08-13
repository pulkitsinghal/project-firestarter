# `datastore_advisor` add-on (contributor notes)

> This file documents the add-on for **firestarter maintainers**. It lives above
> `common/`, so the generator does **not** stamp it into projects. The
> user-facing docs are `common/docs/DATASTORE_ADVISOR.md`,
> `common/docs/DATASTORE_DECISION.md` and
> `common/tools/datastore_advisor/README.md`, which *do* stamp.

## What it is

A **stack-agnostic**, opt-in (default `no`) add-on that makes "where should this
project's data live?" an explicit, documented decision instead of an inherited
default.

Every stack profile ships a datastore because it has to ship *something*. That is
a scaffolding convenience, and it quietly becomes an architecture. This add-on
gives a project the means to make the choice deliberately, argue it against its
own idea, security needs, and workload, and commit the reasoning next to the
code.

It ships a decision guide, a stdlib-only elicitation tool, and a decision-record
template. It does **not** provision, configure, or migrate anything — it is
advisory, and stamping it changes no infrastructure.

## Layout (all under `common/`, stamped to `<project>/`)

```
common/docs/DATASTORE_ADVISOR.md              the decision guide (the durable prose)
common/docs/DATASTORE_DECISION.md             seed decision record, replaced by the tool
common/tools/datastore_advisor/README.md      stamped quickstart
common/tools/datastore_advisor/__init__.py
common/tools/datastore_advisor/questions.json the elicitation axes, in deliberate order
common/tools/datastore_advisor/catalog.json   engines: fits, wrong_for, edition_traps, exit_cost, citations
common/tools/datastore_advisor/advisor.py     the decision engine
common/tools/datastore_advisor/cli.py         interview + rendering + --explain
common/tools/datastore_advisor/selftest.py    offline self-test (no network)
```

## Design notes

- **Not a quiz.** There is no weighted score and no single verdict number,
  because a total hides the reason and the reason is the entire product. The
  engine disqualifies with stated rules, argues both sides, emits verification
  tasks, and names falsifiers. `Recommendation.case_against` is never empty.
- **Biased toward boring.** For ordinary workloads it recommends a single
  Postgres instance and says so plainly. Steering users away from
  over-engineering is a feature; a tool that manufactured sophistication would be
  worse than none. The self-test asserts this rather than trusting it.
- **"Do you even want to hold the data?" is axis zero.** Not a footnote — the
  first question asked, because it changes every answer below it, and because
  device-local or client-encrypted storage removes a liability class rather than
  managing it. The self-test asserts it is ordered first.
- **"Unknown" is first-class** on nearly every axis and comes back as a
  measurement task. An unmeasured workload is an argument for the most *portable*
  option, never the biggest one.
- **Two unconditional verifications.** The edition check and the restore drill
  are emitted on every run regardless of answers, and escalate to blocking in the
  cases that warrant it. A recommendation is not `operationally_ready` while a
  blocking verification is outstanding.
- **The `wrong_for` list is the product.** A pitch for any of these engines is
  one search away; an honest disqualification is not. `selftest.py` fails any
  catalog entry that lacks one.
- **Citations carry URL + date read.** Pricing and capabilities move. Where
  something is not publicly documented the catalog says "not public" rather than
  inventing a figure — see the Supabase compliance add-on price and the two Neon
  pages that disagree with each other, both recorded as-is.

### The edition trap

The guide's central reusable lesson, and the reason the add-on exists in this
shape: **verify the edition you will actually run has the feature you are
choosing the engine for.**

Free and community editions routinely omit precisely the properties teams select
an engine for — separate databases, role-based access control, fine-grained
authorisation, online backup, audit logging. The edition installed to evaluate a
thing is the one that quietly stays in production. Nothing in normal operation
reveals the gap; it surfaces in a security audit, long after the schema and every
query have been written around the assumption.

The guide makes this checkable with a cited vendor example (Neo4j's operations
manual on Community vs Enterprise: one standard database, no RBAC, offline backup
only, GPLv3), and generalises it to managed services, where the equivalent
question is *which plan* — compliance agreements, restore windows, and audit
logging are routinely plan-gated.

The engine escalates this verification to **blocking** whenever the user says an
isolation, security, or compliance property is part of *why* they are choosing an
engine, and refuses to confirm the choice on the strength of the engine's name.

## Tokens

Uses only `{{ project_name }}` and `{{ project_slug }}`, both already declared in
`firestarter.config.json`. No new tokens.

Note that `__init__.py` carries tokens, so the **raw** template file is not
meaningful Python until substitution — same convention as the `local_ollama`
add-on. Firestarter's own CI never compiles addon sources directly; the *stamped*
copy is what gets compiled and self-tested.

## Verify

```bash
# Straight from the add-on source
python3 addons/datastore_advisor/common/tools/datastore_advisor/selftest.py

# Contract test: stamps every stack, runs the stamped self-test, asserts removal
python3 -B -m unittest -v tests.test_datastore_advisor_contract
```

Stamp with `--set include_datastore_advisor=yes` and confirm no `{{` leaks. CI
runs both, plus the off-by-default assertion.
