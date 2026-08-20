# `version_changelog` add-on (contributor notes)

> Maintainer notes. This file sits above `common/`, so the generator does **not**
> stamp it into projects. The user-facing doc is `common/docs/VERSION_CHANGELOG.md`,
> which *does* stamp into `<project>/docs/`.

## What it is

A **stack-agnostic** add-on that turns the build stamp every project already prints
into a changelog and a rollback control. One custom element, no dependencies, no build
step, Shadow DOM so it survives contact with any host stylesheet — including a Claude
artifact under strict CSP, where it can be fed an inline manifest instead of fetching one.

## Layout (all under `common/`, stamped to `<project>/`)

```
common/assets/version-changelog.js   the <version-changelog> element (~330 lines, no deps)
common/scripts/changelog-gen.py      draft → review → publish pipeline
common/docs/VERSION_CHANGELOG.md     concept, manifest shape, wiring, a11y
```

## The two design decisions worth defending

**1. Publication fails closed.** The generator's `include` heuristic is a proposal.
On its first real run against `cervical-cord-video` it proposed *"Audio drifted from its
beat when a beat was inserted"* for publication — a true and completely internal
sentence. So `publish` refuses any release whose `reviewed` flag is still false, and
refuses outright if `_`-prefixed internal fields would reach the output. The heuristic
saves typing; it is not the gate.

**2. The component never mutates.** It opens an immutable URL, or it emits a cancelable
`changelog:rollback` event. Rollback availability is supplied by the project's rollback
map, never inferred — because the component cannot know whether a version is separable
from server state, and guessing wrong means offering a restore that silently half-works.
Disabled entries must carry a reason, and the reason is rendered as visible text, not
just a tooltip.

## Where the rollback URLs come from

Most static hosts already mint an immutable per-deployment alias and simply do not
advertise it:

| Host | Immutable alias |
|---|---|
| Cloudflare Pages | `https://<deploy-hash>.<project>.pages.dev` |
| Netlify | `https://<deploy-id>--<site>.netlify.app` |
| Vercel | the per-deployment `*.vercel.app` URL |
| S3 / R2 | object versioning (`?versionId=`) |

These are the *same* URLs that are a hazard when shared by accident — a frozen build
someone keeps opening forever. Enumerated deliberately, that hazard becomes the feature.

## Gotchas

- **Inline manifests need escaping discipline.** The element reads `textContent`, so a
  `</script>`-like sequence inside a note will not bite, but unescaped user content in
  notes would; everything rendered goes through `escapeHtml`.
- **`document.addEventListener(..., true)`** — the outside-click handler uses the capture
  phase deliberately. A host that calls `stopPropagation()` on its own clicks would
  otherwise leave the panel stuck open.
- **No `<dialog>`.** Native dialog's top-layer behaviour fights position-anchored panels
  inside transformed ancestors, which several of our pages have.
- The stamp inherits `font-family` from the host by default; pin `--changelog-sans` if the
  host font is decorative.

## Try it

```
python3 common/scripts/changelog-gen.py draft --repo /path/to/repo --out draft.json
# edit draft.json: fix the wording, flip reviewed:true
python3 common/scripts/changelog-gen.py publish --draft draft.json --out changelog.json \
        --rollback-map rollback.json
```

`examples/version-changelog/` renders a page with both a fetched and an inline manifest,
including a deliberately disabled release, for eyeballing the states.
