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
The installed manifest must declare `"mcpServers": "./.mcp.json"`; retaining
the default `hooks/hooks.json` without that pointer or either referenced hook
adapter is an invalid partial installation.

Before any launch/refill operation, use the installed plugin's owner-operated
bootstrap command to pin one clean compatible Firestarter worktree:

```bash
python3 scripts/configure_runtime_pin.py \
  --project-root /absolute/clean/firestarter-runtime
```

The command writes mode `0600`
`~/.codex/orchestrator-state/runtime-pin.json`. The pin covers the control CLI,
version, every schema, root-role guard, and runtime verifier. It contains no
credential, prompt, task, or private-record data. Subsequent typed MCP calls may
omit `project_root`; an explicit different path or any content drift fails
closed before the control CLI runs.

Use a hook-untrusted bootstrap task for discovery. Before trusting the hook or
assigning `ROOT_ORCHESTRATOR_ROLE=trusted-project-hook`, confirm that the exact
installed version exposes `pm_proxy_verify_runtime`, `pm_proxy_doctor`,
`pm_proxy_status`, `pm_proxy_prepare_launch`,
`pm_proxy_record_launch_receipt`, `pm_proxy_lifecycle_watchdog`,
`pm_proxy_reconcile_expired_lease`,
`pm_proxy_close_and_refill`, `pm_proxy_watchdog_refill`,
`pm_proxy_slot_status`, `pm_proxy_record_refill_receipt`, and
`pm_proxy_record_archive_receipt`, then run typed `doctor`. Firestarter does not
stamp a project `.codex/hooks.json`; an adopting managed wrapper may assign the
trusted root role only after this bootstrap gate succeeds.

Treat these as separate gates:

1. source validation and hashes;
2. repository marketplace inclusion;
3. plugin installation/adoption;
4. typed MCP discovery plus exact runtime pin and trusted project-hook adoption;
5. dispatcher integration that routes every protected tool through the guard;
6. a real host denial/create/receipt/lifecycle/archive test proving the covered
   underlying calls and fences behave exactly as claimed.

Keep root-role enforcement inactive during gates 1-3. Source and Docker tests
must include adversarial held-lock, stale-ledger, archive-replay, malformed
state, and missing-component cases before any candidate is installed on a host.
Launch, close/refill, and watchdog-refill remain disabled until both the pin and
a current-version covered-path adoption receipt exist.

Passing an earlier gate does not prove a later one. This artifact performs no
personal installation or live configuration mutation.

## Partial-activation recovery

If the root guard fires but the `pm_proxy_*` tools are absent, stop. That task
cannot safely repair its own enforcement path because Bash, patch, filesystem,
and unreserved task creation are intentionally denied.

From an owner-controlled terminal outside the blocked task, restore the exact
previous project `hooks.json` or move the newly added project hook aside. Do not
rename or delete the plugin's source `hooks/hooks.json`. Fully restart Codex,
return to a hook-untrusted bootstrap task, and repair or reinstall the complete
plugin. Re-arm only after the manifest pointer, MCP discovery, typed `doctor`,
and exact hook definition all agree. This recovery changes no Firestarter
SQLite state and must not release, replace, or fabricate any reservation.

## Update

Validate the candidate source first. Preserve its semantic version and use the
plugin-creator `update_plugin_cachebuster.py` helper for iterative local
reinstalls rather than editing marketplace JSON by hand. Reinstall from the
configured local marketplace name, then test in a new task.

Every plugin version change invalidates the prior runtime pin and dispatcher
adoption for automatic-control readiness. Re-run the pin command against the
same reviewed clean runtime, repeat the live covered-path proof, and record a
new adoption receipt carrying the installed version. Doctor/status and exact
expired-lease repair remain available while automatic launch/refill is denied.

For a Firestarter adoption, sync a new isolated branch from the then-current
`master`, reapply the narrow overlay, regenerate hashes, run Firestarter's full
all-stack contract, and open a normal PR. The included ac608 patch is retained
as historical review evidence only; do not apply it to newer source.

## Rollback

Retain the prior verified source archive and hashes until the new plugin passes
task-level smoke tests. To roll back, restore the prior extracted source tree,
reinstall the same plugin name from the configured local marketplace, and start
a new task. Recreate the runtime pin with that restored plugin version; never
copy or relax a mismatched pin. Do not roll back or replace the Firestarter
SQLite state database.
If a new schema migration occurred, stop and follow the matching Firestarter
rollback procedure instead of copying an older database over it.
