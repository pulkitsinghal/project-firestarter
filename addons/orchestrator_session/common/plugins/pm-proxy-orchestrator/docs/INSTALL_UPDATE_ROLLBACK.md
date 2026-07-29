# Install, update, and rollback

This artifact is not installed by its build process.

## First team/repo installation

Verify the source archive and `SHA256SUMS`, extract it into an isolated
repo/team directory, and inspect `.agents/plugins/marketplace.json`. Because this
is a non-default marketplace path, configure that marketplace root explicitly:

```bash
codex plugin marketplace add /absolute/extracted/artifact-root
codex plugin add pm-proxy-orchestrator@project-firestarter
```

Start a new Codex task after installation so the skill is reloaded. Do not copy
the entry into a personal marketplace unless that is separately intended.

Treat these as separate gates:

1. source validation and hashes;
2. repository marketplace inclusion;
3. plugin installation/adoption;
4. dispatcher integration that routes every protected tool through the guard;
5. a real host end-to-end denial test proving the underlying call count is zero.

Passing an earlier gate does not prove a later one. This artifact performs no
personal installation or live configuration mutation.

## Update

Validate the candidate source first. Preserve its semantic version and use the
plugin-creator `update_plugin_cachebuster.py` helper for iterative local
reinstalls rather than editing marketplace JSON by hand. Reinstall from the
configured local marketplace name, then test in a new task.

For a Firestarter adoption, sync a new isolated branch from the then-current
`master`, reapply the narrow overlay, regenerate hashes, run Firestarter's full
all-stack contract, and open a normal PR. The included ac608 patch is retained
as historical review evidence only; do not apply it to newer source.

## Rollback

Retain the prior verified source archive and hashes until the new plugin passes
task-level smoke tests. To roll back, restore the prior extracted source tree,
reinstall the same plugin name from the configured local marketplace, and start
a new task. Do not roll back or replace the Firestarter SQLite state database.
If a new schema migration occurred, stop and follow the matching Firestarter
rollback procedure instead of copying an older database over it.
