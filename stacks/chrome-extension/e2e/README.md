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
`chrome-extension://<id>/sidebar.html`. Grow `specs/` with your real flows; add
content-script coverage by serving a fixture page and asserting the injected
behaviour.
