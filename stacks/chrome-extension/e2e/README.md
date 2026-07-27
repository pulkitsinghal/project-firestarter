# {{ project_name }} — end-to-end tests

Playwright drives a **real headed Chromium** with the built extension loaded, so
these run on the **host**, not in the tools container (a headless container can't
load an MV3 extension). That's why e2e is not a *required* CI gate.

**CI:** run it from the Actions tab via the opt-in workflow
`.github/workflows/e2e.yml`, which runs the suite on a display-less runner using
Xvfb (`e2e/scripts/with-xvfb.sh`) plus container-safe Chromium flags
(`--no-sandbox`, `--disable-dev-shm-usage`, set in `fixtures/extension.ts`). It's
`workflow_dispatch` only, so it never blocks auto-merge.

## Run

```bash
make build                      # build the extension → ../extension/dist
cd e2e
npm install
npm run playwright:install      # one-time: fetch the Chromium build
npm run test:e2e
```

## How it works

`fixtures/extension.ts` launches a persistent Chromium context with
`--load-extension=<extension/dist>`, then resolves the extension id from the
background **service worker's** URL. The `sidebarPage` fixture opens
`chrome-extension://<id>/sidebar.html`.

The second smoke drives the compiled content script against
`test-pages/navigation/`, a synthetic hostile page containing untrusted
instructions, an accessible-name override, responsive duplicate links,
different-URL ambiguity, a hidden decoy, and a JavaScript URL. It verifies the
read-only status boundary; the scaffold deliberately does not navigate.

## Toolbar-attached acceptance

Opening `sidebar.html` directly is useful integration coverage, but it is not
equivalent to Chrome attaching the side panel to a real tab. The extension page
can become the active tab and mask `currentWindow` or active-tab coupling bugs.
Playwright cannot reliably click the native extension toolbar or permission
bubbles.

Before releasing a toolbar-driven product, run a separate human smoke in branded
Chrome: open the synthetic fixture, click the actual toolbar action, verify the
panel is attached to that tab, and repeat the unique/ambiguous/hidden/unsafe
cases. See `docs/BROWSER_ASSISTANT.md` for the full release ladder.
