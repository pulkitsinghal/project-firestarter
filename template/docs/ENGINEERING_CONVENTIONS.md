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

- **It is authoritative.** If hosted CI produces no substantive proof because
  it is unavailable or infrastructure prevents the intended check from
  executing, the green local gate still stands as the quality signal. This never
  licenses reclassifying an executed hosted failure or a **BLOCKING** review
  verdict — those are real and must be resolved.
- **Nothing beyond review + the pyramid is required** to validate code quality.
  Don't hold merge-ready work waiting for a review layer the gate already covers.
- **Name which layers exist and ran.** A stack that lacks a layer (a DB-less
  stack has no integration-DB tests, a library has no e2e) says so — it does not
  silently skip the gate.

### CI integrity: unexecuted is not green

Hosted CI is green only when the intended required proof for the exact candidate
was dispatched, executed, and completed successfully. A configured workflow or
a historical success is not current evidence.

| Hosted-check state | Truthful classification |
|---|---|
| Intended required proof completed successfully for the exact candidate | Green |
| Check absent, disabled, or not dispatched | Unexecuted—not green |
| Execution blocked by billing/quota state or runner unavailability | Unexecuted or unavailable—not green |
| Queued or pending | Incomplete—not green |
| Failed, canceled, or timed out | Unsuccessful—not green |
| Explicitly optional check whose trigger does not apply | Not applicable—not passed or green |
| Zero substantive proof steps executed | Unexecuted—not green |

Keep local and hosted evidence separate. Only when hosted CI produced no
substantive proof may the local gate supply the quality signal; record both
facts: “local gate passed; hosted CI unexecuted,” plus the reason. The local run
is authoritative quality evidence only when it is the documented equivalent
gate, runs on the exact candidate, proves current-source visibility, covers every
applicable test-pyramid layer, and names any inapplicable layer. An ad hoc subset,
stale candidate, or silently skipped layer is not equivalent. A local pass never
overrides an executed hosted failure and never claims to satisfy or bypass the
repository host's merge policy.

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

## 8. Adopt canonical process code with a parity lock

Consolidating duplicated process or infrastructure code is a behavior change
until evidence proves otherwise. **Adopt the canonical implementation; do not
re-implement it from memory.** Use this sequence before retiring a working local
copy:

1. **Name the observable contract.** Build a sanitized, synthetic fixture that
   contains no credentials, private records, production data, or proprietary
   inputs. Make volatile values deterministic at their source. When a format
   genuinely permits multiple byte encodings, define and review one narrow
   canonicalizer before the comparison; never delete mismatches, strip unknown
   fields, reorder output after the fact, or broadly normalize until a test
   passes.
2. **Land the golden parity lock before the switch.** Run the local and canonical
   implementations against the same fixture and compare their observable output
   byte-for-byte, including encoding, order, whitespace, and line endings. Prove
   the assertion can fail with a deliberate mismatch. If raw byte parity is
   impossible, compare the previously defined canonical bytes and record the
   exact reason. If nondeterminism cannot be isolated safely, use explicit
   semantic invariants and do **not** claim byte parity. "The tests look
   equivalent" is not parity evidence, and fixture parity samples the declared
   contract—it is not proof of exhaustive behavioral equivalence.
3. **Vendor a pinned canonical copy first.** Record an immutable source commit,
   or resolve a package version to an artifact locked by digest/integrity
   metadata—a human-readable version alone is not immutable provenance. Vendored
   binary assets also need a digest manifest and a release gate that verifies
   shipped bytes against both their source copy and that manifest. An unversioned
   copy-paste is a new fork, not adoption.
4. **Route consumers through one thin local shim or re-export.** Keep the public
   import stable. First make the shim expose the existing implementation; after
   the parity lock is green, change a single import/export seam to the pinned
   canonical copy. Do not scatter direct canonical imports through consumers.
5. **Keep rollback one seam wide.** Retain the local implementation until its
   original tests and every adopting consumer are green. Rolling back during the
   transition means changing the shim back, not reconstructing deleted code.
   Remove the old copy only after acceptance; a later registry/package swap stays
   behind the same seam.

For deterministic release assets, run the shipped content-suppressed guard in
the release pipeline after building and before publishing:

```bash
scripts/verify-release-parity.sh --pairs config/release-pairs.tsv
scripts/verify-release-parity.sh \
  --vendor-manifest config/vendor.sha256.tsv \
  --vendor-source vendor/source --vendor-release dist/vendor
make release-parity \
  RELEASE_PARITY_PAIRS='config/release pairs.tsv'
```

The pair manifest is `source/path<TAB>release/path`. The vendor manifest is
`lowercase-sha256<TAB>path-relative-to-vendor-roots`; it must describe the exact
regular-file inventory in both roots. Missing, extra, duplicate, malformed,
case-drifted, absolute/traversing, symlinked, unreadable, hash-mismatched, and
byte-mismatched entries fail closed; identical, nested, or hard-linked source and
release boundaries are also rejected as false proof. Diagnostics print no paths,
content, URLs, or hashes. A digest stored beside a blob proves reviewed-byte integrity, not
independent publisher authenticity. Publish only asset names and inventories
that are already safe and licensed to disclose.

Run the guard from a trusted, quiescent checkout and keep the manifests stable
for the duration of the check. Portable Bash validates each manifest before and
after opening it, then consumes the retained descriptor, so removing the path
after it is open does not change the bytes being checked. It does **not** claim
protection from a concurrent same-user replacement between those checks; a FIFO
substitution can also block at open. Do not mutate release inputs concurrently,
and retain the pipeline's ordinary job timeout. A hostile shared workspace needs
a separately reviewed platform sandbox or identity-verifying helper.

Release parity proves the local artifact was assembled from declared bytes. It
complements rather than replaces post-deploy `scripts/verify-live.sh`, which
proves collaborators can fetch the intended build from every live hostname.
The `make release-parity` target is an opt-in release-pipeline seam in every
stack. It exports structured `RELEASE_PARITY_PAIRS` / `RELEASE_VENDOR_*`
variables directly to the guard. Each Make value is frozen from its raw,
unexpanded form before export, so Make expressions, shell syntax, spaces, and
dollar signs inside a path remain data; the target fails until those variables
name a real manifest rather than manufacturing an empty green check.

Separate **equivalence** from **improvement**. First prove the canonical port
matches the origin. Then make any intentional hardening or generalization in a
separate reviewable change that updates the contract and fixture and names its
improvement delta. Otherwise a desirable improvement can hide an accidental
regression inside the extraction.

Keep a source-of-truth comparison table while adoption is in flight:

| Responsibility | Local path/ref | Canonical path/ref | Fixture + parity test | Consumer seam | Status + rollback |
|---|---|---|---|---|---|
| Example process step | legacy implementation | pinned shared implementation | synthetic golden fixture | thin local shim | local / canonical / retired; switch shim back |

The table is a migration receipt, not permanent duplication. Delete it only
after the canonical source, consumer seam, parity evidence, and rollback route
are documented somewhere durable. In a public repository, use sanitized opaque
references that reveal no private repository relationship or internal path; if
that would erase useful provenance, keep the detailed table in the private
origin and publish only a generic adoption status.
