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
`pm_proxy_configure_capacity`,
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
Capacity reconfiguration, launch, close/refill, and watchdog-refill remain
disabled until both the pin and a current-version covered-path adoption receipt
exist.

Passing an earlier gate does not prove a later one. This artifact performs no
personal installation or live configuration mutation.

For Codex Desktop, use the bundled owner-operated
`scripts/desktop_host_adapter.py` only after gates 1-4 pass. It binds one exact
existing task ID as root through a dedicated app-server proxy and private
attestation socket; it does not set a global root role. Its `verify` command
must produce a fresh native-hook denial proof before `launch` will start an
isolated Desktop data directory. The adapter itself passes and observes the
private command-line `--user-data-dir`; do not substitute a local launcher shim.
Follow `docs/DESKTOP_HOST_ADAPTER.md`, retain the normal Desktop app as the
recovery path, and withhold dispatcher adoption until the complete live fence
test passes.

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

For an adapter-hosted task, first run the adapter's `stop` command from that
same owner terminal. It disarms the private session before signaling only its
recorded processes and does not change global Codex configuration. If the
isolated window remains visible, close that window only; the ordinary Desktop
app remains unarmed.

## Update

Validate the candidate source first. Preserve its semantic version and use the
plugin-creator `update_plugin_cachebuster.py` helper for iterative local
reinstalls rather than editing marketplace JSON by hand. Reinstall from the
configured local marketplace name, then test in a new task.

For the `0.3.6` to `0.4.0` rollout, first stop the exact `0.3.6` isolated host
with its matching adapter. Install plugin `0.4.0` and control bundle `1.4.0` as
one reviewed unit, run idempotent `init` to add authority metadata and transfer
tables, recreate the runtime pin, and repeat the complete long-lived Desktop
canary and covered-path adoption. Do not migrate live authority until the new
host passes. Federation additionally requires two drained source ledgers, their
exact hosts disarmed, an empty successor state, and the owner-operated
`federation_transfer.py` flow. Abort is safe only before source demotion;
post-demotion recovery resumes forward.

For the `0.3.5` to `0.3.6` Desktop rollout, preserve this exact order:

1. stop the recorded `0.3.5` isolated host with the matching installed `0.3.5`
   adapter before replacing plugin files; never ask a `0.3.6` adapter to stop
   an old session;
2. install the complete reviewed `0.3.6` bundle and compatible clean control
   bundle `1.3.6` as one unit;
3. from an owner terminal, run the new bridge's idempotent `init` once against
   the existing private state so the additive capacity replay table exists;
4. recreate the content runtime pin, perform prompt-untrusted tool discovery and
   typed doctor, repeat the prompted bootstrap/covered-path adoption proof, and
   launch a fresh isolated adapter session;
5. read typed status, then call `pm_proxy_configure_capacity` with one unique
   request ID, its exact returned revision, expected capacity `4`, requested
   capacity `8`, coarse evidence, and explicit UTC time;
6. require exit `0`, verify the committed revision and a fresh status showing
   capacity `8`, then prepare four additional workers as separate fenced
   operations. Receipt-derived status must reach exactly eight active-or-reserved
   workers; a concurrent ninth reservation must fail `CAPACITY_FULL`.

Any failure stops before the next step. The capacity transaction never launches
or refills a task, and the operator must not emulate it with a SQLite update.

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

Desktop host session schemas are version-bound. Stop an active host with the
matching adapter before updating or rolling back plugin source. Never transplant
its capability token or edit an old session file to satisfy a new adapter.

For a deterministic capacity-only rollback from `8` to `6`, first finish or
receipt-fence workers until active-or-reserved occupancy is at most six. While
the `0.3.6` covered path is current, read a fresh status and use one new typed
compare-and-set request with its exact revision, expected capacity `8`, and
requested capacity `6`; require exit `0` and verify fresh status reports six.

For a direct capacity-only rollback from `8` to `4`, first reduce receipt-backed
occupancy to at most four, then use a different unique request with fresh exact
status, expected capacity `8`, and requested capacity `4`; require exit `0` and
verify fresh status reports four. If capacity has already moved from `8` to `6`,
the later request must instead expect `6` and request `4`. Never reuse or edit a
prior request, bypass the occupancy floor, or change SQLite directly.

For a full bundle rollback, complete the capacity rollback to four first. Then
stop the `0.3.6` host with the matching `0.3.6` adapter, restore the complete
retained `0.3.5` bundle/runtime, recreate its matching pin and covered-path
adoption, and launch its matching host. Keep the migrated database; the additive
replay table is harmless to older code and must not be removed or replaced with
an older database copy.
