# Operational dashboard web prototype

A dependency-free, compact renderer for a **sanitized remote snapshot**. Its
committed fixture demonstrates ten dense lifecycle lanes, five resource cards,
explicit test evidence, and privacy/exposure signals across desktop and narrow
screens. It is
the web half of a cross-platform operational-dashboard pattern; the canonical
contract and native implementation live in the separately owned
`prototypes/operations-dashboard/` contribution.

## Boundary

This prototype renders only an explicitly supplied snapshot with:

- `mode: "sanitized-remote"`;
- `queue`, `tests`, `resourceBudget`, and `signals` record collections;
- `exposure: "sanitized"` on every record; and
- an explicit `verification` value on every record.

It deliberately contains no endpoint, URL, host, IP, filesystem-path,
credential, secret, token, personal, or production fields. It does not poll,
open a WebSocket, read device telemetry, or connect a browser to a workstation.
The included fixture is synthetic and exists only to demonstrate rendering.

The renderer fails closed when the snapshot mode or record exposure is wrong,
or when a forbidden field name appears anywhere in the payload. Local-only
records must be filtered before a snapshot reaches this web component.
Rendering uses DOM text nodes rather than HTML interpolation. Missing
collections render an explicit empty state, absent resource measurements do not
produce a meter, and unrun or unimplemented checks are never relabeled as
passing.

The web validator also accepts six coordinated, additive queue fields while
remaining strict about every other unknown field: paired
`completedSteps`/`totalSteps`, `currentStep`, `lastActiveSeconds`, `memoryMB`,
and `cpuPercent`. Legacy records without these fields remain valid. The static
ten-lane view does not infer or display those optional local scheduling values.

## Files

| File | Purpose |
|---|---|
| `index.html` | Accessible page shell |
| `styles.css` | Dense, responsive dashboard layout |
| `dashboard.js` | One-shot validation and rendering |
| `fixtures/sanitized-remote.snapshot.json` | Synthetic privacy-neutral fixture |
| `tests/test_privacy_contract.py` | Contract-shape and privacy-boundary tests |
| `tests/dashboard.test.mjs` | Executable validator and missing-evidence unit tests |
| `tests/browser-smoke.mjs` | Reproducible fail-closed, injection, maximum-text, and responsive browser gate |
| `docs/state-flow.md` | Compact rendering/failure-flow map and still-frame walkthrough |
| `docs/media/` | Rebuilt desktop and narrow-screen browser evidence |

## Validate

Run the dependency-free tests in a throwaway container:

```bash
docker run --rm -v "$PWD:/repo:ro" -w /repo python:3.12-slim \
  python -m unittest discover \
  prototypes/operations-dashboard-web/tests -v

docker run --rm -v "$PWD:/repo:ro" -w /repo node:22-slim \
  node --test prototypes/operations-dashboard-web/tests/*.test.mjs

docker run --rm --ipc=host \
  -v "$PWD:/repo:ro" -w /repo \
  mcr.microsoft.com/playwright:v1.58.2-noble \
  bash -lc 'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install --prefix /tmp/dashboard-pw --no-save playwright@1.58.2 >/tmp/dashboard-pw-install.log && PLAYWRIGHT_MODULE=file:///tmp/dashboard-pw/node_modules/playwright/index.mjs node prototypes/operations-dashboard-web/tests/browser-smoke.mjs'
```

To inspect the static prototype without installing a host SDK:

```bash
docker run --rm -p 8080:8080 -v "$PWD:/repo:ro" -w /repo python:3.12-slim \
  python -m http.server 8080 -d prototypes/operations-dashboard-web
```

The fixture is loaded once. The offline publisher documented in
`../operations-dashboard/PUBLISHING.md` creates a verified, immutable static
bundle containing a contract-valid sanitized snapshot. It never connects this
surface to the native app. Adding a local agent, telemetry bridge, or automatic
refresh is a separate security decision and is not implemented here.

The checked-in browser frames were captured from the rebuilt static prototype
with the synthetic fixture. Video is N/A: this reference has no named,
Dockerized release-cut harness, so the evidence bundle uses the desktop and
narrow-screen still walkthrough in `docs/state-flow.md`.
