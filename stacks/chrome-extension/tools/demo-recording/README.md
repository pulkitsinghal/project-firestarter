# Demo / QA recording — capture the real side panel as video

Playwright's per-page `video` records the **tab**, not the extension's **side
panel** (a separate `chrome-extension://…/sidebar.html` surface) and not the
**cursor**. This tool captures the whole scene — host page **+** panel **+**
visible cursor — as an mp4, with **no login and no backend**. It complements the
`storyboard/` harness (which does per-page screenshots): use storyboard for
planned-vs-implemented stills, use this for a moving release/QA clip.

## The method (why it works)

1. **Iframe the live panel.** `sidebar.html` is a `web_accessible_resource` for
   `<all_urls>`, so a staged host page can `<iframe src="chrome-extension://<id>/sidebar.html">`.
   Now the host page **and** the panel are **one** Playwright page.
2. **Record with Playwright `recordVideo`, not `ffmpeg x11grab`.** Because it's
   one page, `recordVideo` captures the render directly and reliably. (x11grab of
   a bare Xvfb display gives **black frames** — the Chrome window isn't composited
   to the X root without a window manager. Don't go down that road.)
3. **Seed auth + data offline.** If your background auth check reads a token/record
   from `chrome.storage` (the common pattern), seed it via the **service worker**
   so the panel renders **signed-in** with demo content — no network, no OTP, and
   **no real account ever on screen**. Mock any read APIs with `context.route(...)`.
4. **Inject the cursor via `addInitScript`.** The panel's CSP (`script-src 'self'`)
   refuses `addScriptTag`; `addInitScript` is delivered over CDP, so it isn't
   subject to the page CSP.

## Files here

| File | What it is | App-specific? |
|------|------------|---------------|
| `record.template.mjs` | Recorder skeleton — copy to `record.mjs`, fill the 4 `CONFIGURE` blocks (auth seed, route mocks, staged page, scene beats) | **Yes** — you fill it in |
| `visual_cursor_overlay.js` | Zero-dependency visible cursor + click ripple + keypress chip. Exposes `window.demoVisualCursor` | No — generic |
| `video_processor.py` | `ffmpeg`/`ffprobe` wrapper: `convert_to_mp4`, `trim`, `concat`, `add_fade`, `get_video_info` | No — generic |

## Quick start

```bash
make build                              # produce extension/dist
cp tools/demo-recording/record.template.mjs tools/demo-recording/record.mjs
# edit record.mjs → fill the 4 CONFIGURE blocks for your app
node tools/demo-recording/record.mjs    # writes tools/demo-recording/.out/scene.webm
```

Stitch multiple scenes + title cards into one clip with `video_processor.py`
(`concat`/`add_fade`). Title cards: render an HTML card in Playwright and
screenshot it, then `ffmpeg -loop 1 -t <sec> -i card.png …` — **do not** rely on
`drawtext` (many Homebrew ffmpeg builds ship without freetype).

## Gotchas (each cost real time)

- **Verify by the pixels, not the log.** A green run routinely produced a **black**
  recording or an empty search while every line said "ok". Take a `page.screenshot`
  checkpoint and *open it*. `record.template.mjs` writes `.out/frame-checkpoint.png`
  for exactly this.
- **`rules.json` modal hang.** Unpacked, Chrome may reject `declarative_net_request`
  rules with a blocking modal → the service worker never registers → everything
  hangs. Load a **sanitized copy** of `dist/` with DNR + `rules.json` stripped (the
  template does this).
- **Tiny `/dev/shm` in containers** makes Chromium hang on launch. Use both
  `--disable-dev-shm-usage` (flag) and a larger shm if you containerize.
- **Site-access banner** gates page reads on unknown origins. Pre-grant the fixture
  origin in the sanitized manifest's `host_permissions` (the template adds
  `http://localhost:4180/*`).
- **Mask secrets in the UI too.** If Settings shows a user id / token / key, the
  product should **mask it by default** (`-webkit-text-security: disc`) with a
  click-to-reveal — dots leave no pixels to un-blur or OCR from a frame. Recording
  around a leak is not enough; fix it at the source.
- **Trademark hygiene.** Name staged pages after **fictional** brands, and hide any
  in-product panel that lists real third-party names, before sharing a clip.
- **Pad the last beat.** The window goes black right after `context.close()` — hold
  the final frame long enough to fill the clip.

## Provenance

Distilled from a sibling chrome-extension project's `demo-recording/LEARNINGS.md`
(iframe + seed-auth + `recordVideo` approach), reduced to the reusable primitives
and a fill-in-the-blanks template. Domain specifics (selectors, API shapes, auth
record format) intentionally stay in the copied `record.mjs`, not here.
