# Storyboard — visual regression aid + planned-vs-implemented map

The storyboard boots the running app and drives it with Playwright (in Docker —
no host Node), capturing a sequence of screenshots **and** rendering a living
"planned vs implemented" doc. It runs:

- **Locally:** `make storyboard` → writes PNGs to `storyboard/output/` and
  regenerates [STORYBOARD.md](STORYBOARD.md) + committed previews under
  `docs/assets/storyboard/`.
- **In CI:** `.github/workflows/storyboard.yml` (non-blocking) uploads the PNGs
  as a build artifact on every PR that touches the UI or backend.

It is intentionally **non-blocking** — it never fails a PR. It exists so a human
(or agent) can *see* what changed without booting the stack locally.

## The manifest (planned vs implemented)

`storyboard/manifest.json` is the hand-edited canonical map of what's planned
vs. built — versions → groups → rows, each with a `status`
(`done`/`partial`/`planned`/`changed`) and an optional captured `shot`. On every
run the harness regenerates `docs/STORYBOARD.md` from it, embedding the
screenshots it captured. **The harness is the source of truth for "what's
implemented"** — editing the manifest and re-running keeps the doc from going
stale.

> Note: the generated doc is `docs/STORYBOARD.md` (uppercase). This explainer is
> `docs/storyboard-harness.md` — deliberately a different name so the two don't
> collide on case-insensitive filesystems (macOS).

## Editing the script

`storyboard/storyboard.mjs` drives the flow. Add a step by navigating and
calling `shot('NN-name')`, then add a matching row in `manifest.json` referencing
`NN-name.png`. Keep step names stable so diffs across runs line up.

## Why screenshots, not pixel-diff assertions

Auto-failing on any pixel change is noisy for an app under active development.
The storyboard makes change *visible and reviewable* instead of *blocking*.
Promote specific flows to hard assertions later if a screen stabilizes.
