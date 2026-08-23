# {{ project_name }} practices

This file holds rules this project earned from its own failures. It is not a
catalog of generic advice and it is not a task list. Read it before designing a
change, making an important claim, or starting expensive production work.

## What belongs here

Add a practice only when all of these are true:

- A concrete failure, near miss, rework cycle, or successful safeguard produced
  the lesson. Link its issue, postmortem, commit, or test when that reference is
  safe to share; otherwise mark the evidence as withheld without copying the
  sensitive detail here.
- The rule will still matter after the current task is complete.
- The wording states both **what it cost** and the generalized rule. Keep
  credentials, private records, customer details, and unnecessary identities
  out; describe sensitive incidents at the minimum safe level.

Tasks stay in `PROJECT_STATUS_AND_NEXT_STEPS.md`. Incident detail stays in
`docs/postmortems/`. A rule that every project would want is a candidate to lift
into shared tooling; this file remains the canonical record of what this project
learned and why.

## Earned practices

No project-specific practices have been earned yet. Replace this sentence when
the first one is promoted. Do not import another project's rules as though this
project earned them.

### Reproduce the failure before repairing it — synthetic example, not earned by this project

**Evidence:** synthetic format demonstration

**What it cost.** A plausible fix was implemented before the original failure
had a repeatable reproduction. The same failure returned, and the team could not
prove whether the first change had addressed it.

**Generalization.** Capture the smallest safe reproduction first, then keep it
as a test or documented verification step that fails before the repair and
passes after it.

Use this shape for a real entry:

```markdown
### <imperative rule>

**Evidence:** <safe reference, or `withheld: sensitive incident`>

**What it cost.** <observable impact; no secrets or unnecessary private detail>

**Generalization.** <portable action or decision test that applies beyond the incident>
```

## Promote stranded rules

At project milestones and after a postmortem, scan recent findings, status docs,
review notes, and commit messages for lessons that are still trapped in the
document where they happened. Promote durable ones here, merge duplicates, and
remove rules whose evidence no longer holds. A bare preference does not become
a practice merely by being repeated.
