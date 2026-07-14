# Feature Handoff — Evidence Bundle

Use this playbook whenever a feature moves from implementation to user/dev
testing, release review, or approval. The receiver should be able to understand
what changed, see that it works, and locate remaining risk without reconstructing
the behavior from a diff.

## Baseline required for every handoff

1. **Outcome and acceptance.** State the intended behavior and exercise the
   primary acceptance path against the rebuilt artifact.
2. **Failure and recovery.** Exercise the most important failure, retry,
   rollback, or cleanup path. If none applies, explain why.
3. **Exact verification.** Record the commands, automated results, live checks,
   environment, and any remaining gap. “Tests pass” is not evidence by itself.
4. **Inspectable evidence.** Provide the closest durable evidence for the work:
   real UI frames, safe request/response examples, redacted logs, build output,
   migration results, or a state transition.
5. **Safe artifacts.** Use synthetic/test fixtures. Never put credentials,
   secrets, private records, production data, browser history, or unrelated
   workstation content in screenshots, recordings, logs, captions, or examples.
   If a feature handles private data, demonstrate it with synthetic stand-ins
   and verify storage/access controls separately without copying the real data.
6. **Self-contained handoff.** Lead with the outcome, identify known limits and
   rollback, and name the next action that requires user authority.

## Visible UI changes

For a visible change:

- update `storyboard/storyboard.mjs` and `storyboard/manifest.json`;
- run `make storyboard` against the rebuilt app;
- keep `docs/STORYBOARD.md` and selected committed preview assets current;
- include entry, success, and meaningful failure/cleanup frames; and
- add a compact Mermaid state/flow map when the feature has a lifecycle. For a
  truly stateless screen, say so and show its request/response path instead.

Also record relevant browser-console errors (or explicitly say there were none).
Mock product screens are not acceptance evidence.

## When to make a release cut

A short captioned release cut is useful for a material, multi-step UI flow, but
it is not a universal completion gate. Make one when the repository already
ships a reproducible Dockerized recipe and named Make target. Otherwise mark
video **N/A — no reproducible harness** and provide an ordered still-frame
walkthrough. Do not install an ad hoc host media toolchain merely to satisfy a
handoff checklist.

When a supported release cut is made:

- keep it short (roughly 20–40 seconds is a useful default);
- use real rebuilt-app frames and readable timed or burned-in captions;
- show entry, success, a meaningful safety/failure state, and final/cleanup;
- use broadly playable H.264/AAC settings when the shipped recipe supports them;
- keep focus/transition effects restrained and synchronized to the UI state;
- treat narration as optional; if included, use clear conversational delivery;
  and
- report the artifact duration, dimensions, codecs, and reproducible command.

Video supplements the stills, state map, and verification record; it never
replaces them. Generated binaries may stay under ignored `storyboard/output/`
unless the release channel explicitly needs a committed artifact. Commit the
recipe and source captions when the project owns such a harness.

## Non-visual features

Do not manufacture UI evidence for backend-only, migration-only, documentation,
or operational work. Mark storyboard/state-map/video N/A with a reason and use
the closest useful evidence: safe request/response pairs, migration and rollback
results, redacted logs, generated-file diffs, build output, or a reproducible
smoke check.

## Firestarter versus a generated project

The storyboard and Make commands above belong to a generated project. When
changing Firestarter itself, stamp the affected stack(s) into a temporary output
directory and exercise the generated commands there; do not pretend the
generator root has a universal app or media target.

## Handoff response shape

1. Outcome and scope.
2. Acceptance plus failure/retry/rollback evidence.
3. New/changed real screens, or non-visual evidence with N/A rationale.
4. State/flow map walkthrough when applicable.
5. Conditional release cut, or its explicit N/A rationale.
6. Exact automated and live verification.
7. Known limitations, release risk, rollback, and next owner action.
