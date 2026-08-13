# Datastore decision record — {{ project_name }}

> **Seed file.** Nothing has been decided yet. Replace this whole file by running
> the advisor:
>
> ```bash
> python3 -m tools.datastore_advisor.cli -o docs/DATASTORE_DECISION.md
> ```
>
> Then commit it. The point of a decision record is that the *reasoning* outlives
> the person who did the reasoning — six months from now, "why are we on this?"
> should have a written answer, including the tradeoffs that were accepted
> knowingly.

## Status

**Not yet decided.** {{ project_slug }} is running on whatever the scaffold
shipped, which is a default rather than a decision.

## What goes here once you run it

The generated record contains:

- **The recommendation**, and whether it is operationally ready.
- **Why** — reasoning grounded in the answers you gave, not generic advice.
- **The case against it** — stated deliberately. If none of it worries you,
  either the fit is genuinely good or the answers were optimistic.
- **What was ruled out, and why** — the rules that fired, so you can disagree
  with them.
- **Alternatives worth pricing** before committing.
- **Verifications to complete before building**, including the two that are
  always emitted: confirm the *edition you will actually run* has the feature you
  are choosing it for, and restore a backup into a working system at least once.
- **What would change this answer** — falsification triggers tied to your
  answers, so this can be revisited on evidence.
- **The answers it was based on**, so a future reader can see what was assumed.

## Backup restore drill

Fill this in. A backup nobody has restored is not a backup.

| Field | Value |
|---|---|
| Date of last successful restore | _not yet performed_ |
| Restored into | _e.g. a fresh empty instance_ |
| Time taken | _._ |
| Application verified against the restore? | _no_ |
| Engine version at time of drill | _._ |

Re-run the drill whenever the engine version or the backup tooling changes.

## Edition / plan verification

Fill this in before writing code against a datastore you chose for a specific
property.

| Field | Value |
|---|---|
| Engine | _._ |
| **Exact edition / plan / version to be run in production** | _._ |
| Property being relied on | _e.g. separate databases per tenant, RBAC, online backup, a signed compliance agreement_ |
| Vendor page confirming that property **for that edition** | _URL_ |
| Date confirmed | _._ |

If you cannot fill in the URL row, the property is not verified — regardless of
what the product's front page says.

## Revision history

| Date | Change | Trigger |
|---|---|---|
| _._ | Initial decision | _._ |

See [DATASTORE_ADVISOR.md](DATASTORE_ADVISOR.md) for the reasoning behind each
axis.
