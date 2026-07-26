# Operational dashboard web prototype

A dependency-free, compact renderer for a **sanitized remote snapshot**. It is
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

## Files

| File | Purpose |
|---|---|
| `index.html` | Accessible page shell |
| `styles.css` | Dense, responsive dashboard layout |
| `dashboard.js` | One-shot validation and rendering |
| `fixtures/sanitized-remote.snapshot.json` | Synthetic privacy-neutral fixture |
| `tests/test_privacy_contract.py` | Contract-shape and privacy-boundary tests |

## Validate

Run the dependency-free tests in a throwaway container:

```bash
docker run --rm -v "$PWD:/repo:ro" -w /repo python:3.12-slim \
  python -m unittest discover \
  prototypes/operations-dashboard-web/tests -v
```

To inspect the static prototype without installing a host SDK:

```bash
docker run --rm -p 8080:8080 -v "$PWD:/repo:ro" -w /repo python:3.12-slim \
  python -m http.server 8080 -d prototypes/operations-dashboard-web
```

The fixture is loaded once. A production adopter should supply a contract-valid
sanitized snapshot through its normal build or static-publish process; adding a
local agent, telemetry bridge, or automatic refresh is a separate security
decision.
