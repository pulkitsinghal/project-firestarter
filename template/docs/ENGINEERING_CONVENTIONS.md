# Engineering Conventions

Reusable, stack-neutral operating conventions that every project on this
scaffold inherits. `AGENTS.md` and `CLAUDE.md` point here; this file carries the
full reasoning. None of it is language- or product-specific — it is *process*.

## 1. The authoritative quality gate: code review + the test pyramid

Merge-readiness has exactly two ingredients, and together they are **sufficient**:

1. **Code review is complete** — the automated PR review (`ai-pr-review.yml`),
   plus your own read-back of the staged diff before you push.
2. **The test pyramid is green, in order:** unit → integration → API →
   end-to-end — each layer the stack actually has.

Run that pyramid **locally, at high intensity, in Docker, mirroring CI** —
`make precommit` plus the stack's integration / API / e2e targets. A green local
gate is the real signal:

- **It is authoritative.** If the hosted CI run is unavailable or flaky for
  reasons unrelated to your change, the green local gate still stands as the
  merge signal. This never licenses ignoring a *genuinely* failing check or a
  **BLOCKING** review verdict — those are real and must be resolved.
- **Nothing beyond review + the pyramid is required** to validate code quality.
  Don't hold merge-ready work waiting for a review layer the gate already covers.
- **Name which layers exist and ran.** A stack that lacks a layer (a DB-less
  stack has no integration-DB tests, a library has no e2e) says so — it does not
  silently skip the gate.

### Quality gate ≠ side-effect gate

Clearing this gate authorizes **merging code**. It does **not** authorize the
owner-only actions in [DEPLOY_POLICY.md](DEPLOY_POLICY.md): deploy / release /
publish, production credentials, prod-DB migrations, spend, destructive history,
or sending on someone's behalf. Those hold no matter how green the tests are.
Merging a well-tested PR never trips one of them, and a green gate is never a
reason to skip one.

## 2. Stacked pull requests — mind the merge order

When PR **B** is *stacked on* PR **A** (B's base branch **is** A's head branch),
the merge order is a trap:

- Running `gh pr merge <A> --squash --delete-branch` deletes A's head branch —
  which is B's base branch — and the platform **auto-closes B**. A closed PR
  cannot change its base or be reopened while its base branch is gone, forcing a
  recovery dance.
- You cannot merge the child first: B's diff includes A's commits.

**Avoid it (in order of preference):**

1. **Retarget the child first.** Point B at the default branch
   (`gh pr edit <B> --base master`), *then* merge A normally.
2. **Or merge the base without deleting its branch.** Merge A **without**
   `--delete-branch`, retarget B onto the default branch, gate and merge B, then
   delete A's branch last.

**Recovery if it already auto-closed** (in an isolated worktree):

```bash
git rebase --onto origin/master <A-head> <B-head>   # drop the now-redundant base commits
# re-run the full local gate on the rebased head
git branch <A-head> origin/master                   # temporarily recreate the deleted base so reopen is allowed
gh pr reopen <B>
gh pr edit <B> --base master
git push --force-with-lease origin <B-head>
# confirm MERGEABLE/CLEAN, squash-merge B, then delete the temp base branch
```

Net change on the default branch = exactly B's intended diff.

## 3. Fork discrete work into its own workstream

When a self-contained unit of work can stand on its own — a refactor you noticed
in passing, an independent fix, a follow-up improvement — **split it into its own
branch/PR** rather than growing the change in front of you.

- Each change stays small, reviewable, and independently mergeable/revertable.
- The current PR keeps a single, clear intent; unrelated risk doesn't ride along.
- **Be proactive.** Don't wait to be asked. If you spot forkable work mid-task,
  hand it off — a tracked issue, a separate branch, or a queued task — instead of
  quietly expanding the diff.

This is the same instinct as "one feature/fix per branch," applied the moment you
notice scope trying to creep.

## 4. Ask for decisions visually, not as a wall of text

When you need a maintainer or owner to **decide** something, don't hand them a
paragraph of prose to parse. Present the decision **visually**:

- Annotated storyboard frames, and/or a short narrated, captioned walkthrough
  with on-screen pointers marking what you're referring to.
- Structure every brief as: **the question → the motivation → what you propose →
  the specific ask.**

Reuse the media conventions in [FEATURE_HANDOFF.md](FEATURE_HANDOFF.md) for any
narrated/captioned cut: keep it short, make it understandable both **muted**
(captions carry it) and **with sound** (a real voice track). A watchable or
quickly scannable brief lets a busy decider decide fast — that is worth the extra
few minutes to produce, and it is the expected format for a decision request, not
an optional flourish.
