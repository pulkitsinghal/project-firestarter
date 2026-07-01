# {{ project_name }} — end-to-end tests

Playwright drives a **real headed Chromium** with the built extension loaded, so
these run on the **host**, not in the tools container (a headless container can't
load an MV3 extension). That's why e2e is not a CI gate — wire an opt-in job once
you have a runner with a display.

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
