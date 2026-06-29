# Storyboard — visual regression aid

The storyboard boots the running app and drives it with Playwright (in Docker —
no host Node), capturing a sequence of screenshots that document the current UI
state. It runs:

- **Locally:** `make storyboard` → writes PNGs to `storyboard/output/`.
- **In CI:** `.github/workflows/storyboard.yml` (non-blocking) uploads the PNGs
  as a build artifact on every PR that touches the UI or backend.

It is intentionally **non-blocking** — it never fails a PR. It exists so a human
(or agent) can *see* what changed without booting the stack locally.

## Editing the script

`storyboard/storyboard.mjs` drives the flow. Add a step by navigating and
calling `shot('name')`. Keep step names stable so diffs across runs line up.

## Why screenshots, not pixel-diff assertions

Auto-failing on any pixel change is noisy for an app under active development.
The storyboard makes change *visible and reviewable* instead of *blocking*.
Promote specific flows to hard assertions later if a screen stabilizes.
