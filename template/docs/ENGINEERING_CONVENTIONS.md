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

## 5. Keep shipped documentation structurally intact

Run `make docs-check` directly, or get it through `make smoke`, `make precommit`,
the docs-only pre-commit path, and CI's **Tests** job. Working mode checks tracked
plus non-ignored untracked Markdown; `--staged` materializes and checks only the
immutable index used by the commit hook. The dependency-free guard requires the
house documents, checks repository-local inline/reference links and simple
single-line quoted HTML `href`/`src` paths, rejects symlink/case/escape/publication
mistakes and unbalanced fenced blocks, and preflights bounded Mermaid structure.
It also keeps `VERSION` aligned with a calendar-valid matching changelog heading.

The Mermaid check is intentionally a **preflight, not a renderer**: it verifies
that a `mermaid` fence starts with an allowlisted diagram type and rejects literal
semicolons in `sequenceDiagram`. [Mermaid uses semicolons as statement
separators](https://mermaid.js.org/syntax/sequenceDiagram.html#entity-codes-to-escape-characters);
Firestarter intentionally rejects even valid semicolon-separated statements as
a one-statement-per-line house rule. Encode a visible semicolon as `#59;`.

Its boundary is equally explicit: external URL reachability, heading-anchor
validity, multiline/full HTML, and full Markdown/Mermaid parsing are not claimed.
Use a real renderer or browser evidence when render fidelity is an acceptance
criterion.

## 6. Pin workflow dependencies immutably

Every remote GitHub Action `uses:` entry must name a full 40-hex commit SHA, with
the intended major version retained as a trailing comment (for example,
`owner/action@<commit> # v4`). A major tag is readable but mutable; a compromised
or retargeted tag otherwise changes executable CI code without changing this
repository. Local `./` actions and `docker://` actions follow their own pinning
rules and are outside this specific check. Keep `uses` as a one-line block key;
sequence-item flow mappings, flow-style `steps: [...]` lists, and flow-style
`uses` keys are rejected. Explicit mapping keys and escaped double-quoted mapping
keys are also rejected. Ordinary data flows such as `branches: [main]` remain
valid. YAML anchors, aliases, and node tags are also disallowed because they
hide action steps behind semantic indirection. The
dependency-free scanner therefore fails closed without claiming to be a YAML
parser.

`make smoke` enforces the immutable-ref shape without a language SDK or printing
the action target. Dependabot's `github-actions` ecosystem owns routine SHA
refreshes in a stamped repository, so immutability does not become permanent
staleness. Firestarter itself additionally keeps an inert root action catalog:
Dependabot can see every action shipped from dormant source directories, and a
parity contract blocks partial propagation. Self-CI also parses every source and
generated workflow as YAML: a malformed workflow that never starts is a failed
gate, never an absent green check.

## 7. Prove Docker gates grade current source

`docker compose run` may reuse an existing image. A tool service therefore sees
the current working tree only while its source bind mount remains intact, or
while its exact runner rebuilds the current context. Losing either mechanism can
leave every test green against an old snapshot—the most dangerous gate failure,
because it looks like success.

Run `make gate-selftest` before the real gates. It plants content-free temporary
sentinels in each source root and invokes the same Make variables the test/lint/
build targets use. The container probe emits two unique observations:

- **runner started + sentinel seen** → that gate grades current source;
- **runner started + sentinel missing** → the gate is **BLIND** and must fail;
- **runner never started** → infrastructure/build failure, with sightedness
  **UNKNOWN**. Never misreport this as blindness or accept it as green.

Visibility markers and wrapper health remain separate facts: a wrapper that
exits non-zero after the probe still fails, while retaining an observed current-
source or BLIND diagnosis rather than rewriting it to UNKNOWN.

The distinction is load-bearing: swallowing runner errors makes an unavailable
Docker daemon look exactly like a removed mount, eroding trust in the real alarm.
Map captured stderr to a fixed privacy-safe category—never echo runner-controlled
bytes that may contain secrets or private paths—remove every sentinel and private
log on pass/failure/signal, and fail closed without printing a path if cleanup
itself fails. Mutation-test both directions with dependency-light fake runners.
The generated **Tests** job runs the guard before project gates, and
`make precommit` lists it first. Do not duplicate a runner command inside the
guard; route optional probe flags through the same Make variable so runner
profile, service, mount/build, and future changes cannot drift.
