# Version stamp, changelog, and rollback

Every project prints a version somewhere — a footer, an about box, a build hash in
the corner. It is almost always dead text. This add-on makes it answer the three
questions a reader actually has:

1. **What am I looking at?** — the stamp itself.
2. **What changed?** — click it; curated notes per release.
3. **Can I go back to the one that worked?** — a restore control, enabled only when
   that is genuinely possible, and disabled with a plain-language reason when it is not.

## Why the curation is mandatory

Commit subjects are written by engineers for engineers. Ours have included lines like
*"audio drifted from its beat when a beat was inserted"* and *"render script screenshotted
a stale slide"* — accurate, useful internally, and not what a collaborator or customer
should be reading in a product changelog.

So the pipeline **fails closed**:

```
changelog-gen.py draft    →  proposes entries from git, marks the obviously
                             internal ones include:false with a reason
        ↓  (a human or an agent reads them as an outsider would)
changelog-gen.py publish  →  emits changelog.json, but ONLY for releases
                             whose reviewed flag is true
```

The `include` heuristic (feat/fix/perf, non-internal scope, no self-flagellating
phrases) is a **first pass, not a filter you trust**. It once proposed the audio-drift
line above for publication. `publish` therefore refuses any release still marked
`reviewed: false`, and refuses outright if internal `_`-prefixed fields would leak.

## Rollback is never guessed

A release is restorable **only** if the project supplies an immutable URL for it in the
rollback map. The natural source is a per-deployment alias — Cloudflare Pages, Netlify,
Vercel and S3 versioning all mint one, and it keeps serving that exact build forever.

```json
{
  "_default_reason": "This version predates the deployment archive.",
  "v1.2.0": { "url": "https://a1b2c3d4.my-project.pages.dev/" },
  "v1.1.0": { "reason": "Restoring this would need the pre-migration database schema." }
}
```

Anything backed by server state — a database migration, a changed API contract, a cloud
function — stays **disabled with the reason shown to the reader**. A greyed button that
explains itself is far better than one that half-works.

The component itself never mutates anything. It navigates to the URL, or emits a
cancelable `changelog:rollback` event and lets the host app decide:

```js
document.addEventListener("changelog:rollback", (e) => {
  if (hasUnsavedWork()) { e.preventDefault(); confirmThenRestore(e.detail.release); }
});
```

## Wiring it in

```html
<script type="module" src="assets/version-changelog.js"></script>

<!-- fetches the manifest -->
<version-changelog src="changelog.json"></version-changelog>

<!-- or inline it, for a strict-CSP page that cannot fetch (e.g. a Claude artifact) -->
<version-changelog>{"title":"Version history","releases":[…]}</version-changelog>
```

### Placement

The stamp can sit wherever the page wants it. `placement` decides whether the component
positions itself or leaves that to the host:

| `placement` | behaviour |
|---|---|
| `inline` *(default)* | sits in normal flow, wherever you mount it — a footer, a header, a sidebar |
| `float` | pins itself like a support launcher; a rounded pill reading "What's new" (override with `floatLabel` in the manifest). `corner` takes `bottom-right` *(default)*, `bottom-left`, `top-right`, `top-left` |
| `header` | pinned top-right |
| `footer` | pinned bottom-right |
| `side` | pinned to the right edge, vertically centred, text running vertically |

Header **and** footer at once is just two mounts — the component is cheap and both read
the same manifest:

```html
<header>… <version-changelog src="changelog.json"></version-changelog></header>
<footer>… <version-changelog src="changelog.json"></version-changelog></footer>
```

Pinned placements open their panel away from the edge they are pinned to, so it never
runs off-screen: bottom-pinned opens upward, top-pinned downward, right-pinned aligns
its right edge, and `side` opens to the left.

Attributes: `src`, `current` (pin which release is "current"; defaults to the first),
`drop="down"` (panel opens downward), `theme="light|dark"`, `target` (window target for
the restore link).

Theming is via CSS custom properties on the host — `--changelog-ink`, `--changelog-surface`,
`--changelog-rule`, `--changelog-accent`, `--changelog-mono`, `--changelog-sans`. The
component uses Shadow DOM, so host stylesheets cannot bleed in and its styles cannot leak
out; it follows `prefers-color-scheme` unless `theme` pins it.

## Manifest

```json
{
  "title": "Version history",
  "stampLabel": "build {id} · {runtime}",
  "releases": [
    {
      "id": "2c5aed27",
      "title": "Age-specific rates",
      "date": "2026-08-20",
      "runtime": "7:04",
      "highlights": ["Added age- and sex-specific rates", "Corrected the age-distribution claim"],
      "rollback": { "available": false, "reason": "This is the version you are viewing." }
    }
  ]
}
```

`stampLabel` interpolates any field of the current release. Order matters: the first
release is treated as current unless `current` names another.

## Accessibility

The stamp is a real `<button>` with `aria-haspopup`/`aria-expanded`; the panel is a
labelled dialog; each release header toggles `aria-expanded` on its notes. Escape closes
and returns focus to the stamp. Disabled restore buttons carry their reason as a `title`
*and* as visible text, because a tooltip alone is not an explanation.
