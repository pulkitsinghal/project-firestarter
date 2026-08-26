# Integration and rollback

## Safe adoption sequence

1. Enable `include_architecture_manifest=yes` and run the bundled hermetic
   validation.
2. Author a manifest for your system using only opaque tokens, the closed
   enums, and repo-relative evidence paths. Keep it next to the code it
   describes. Validate it with `load_manifest`.
3. Render the Mermaid and ANATOMY artifacts with `render_mermaid` /
   `render_anatomy` and commit them alongside the manifest.
4. Add a CI step that re-renders from the manifest and runs `check_drift`
   against the committed artifacts, failing the build on a `stale` or
   `malformed` verdict.
5. Optionally emit the render envelope and drift report as CI artifacts for
   review; both are closed, content-minimized JSON.

Steps 2–5 are author/CI decisions. This add-on ships only the contract, the
renderers, the drift check, and their hermetic tests.

## Rollback

The add-on is default-off and isolated under `tools/architecture_manifest/`.
To remove it from a generated project, delete that directory and any manifest
or CI step you added later. To stop stamping it, omit the include flag or set
it to `no`.

For a Firestarter source rollback, revert the single feature commit or remove:

- the `include_architecture_manifest` config entry;
- the add-on registration in `bin/generate.py`;
- `addons/architecture_manifest/`;
- the matching CI contract test and documentation entries.

No database, browser, permission, service, account, network resource, model, or
deployment is created, so version 0.1 has no external cleanup.
