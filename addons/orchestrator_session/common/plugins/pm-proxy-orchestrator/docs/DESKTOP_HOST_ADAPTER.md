# Codex Desktop host adapter

Version `0.4.12` includes an opt-in desktop host adapter for one exact root task.
It does not export `ROOT_ORCHESTRATOR_ROLE` to the normal desktop process and it
does not infer root identity from a prompt, working directory, project, or
model-visible field.

The owner supplies the exact existing root task ID. The adapter launches a
separate Electron data directory and acts as the CLI path selected by Codex
Desktop. It accepts only a foreground `app-server` invocation (plus Desktop's
bare `--version` probe, answered from the recorded real CLI), proxies the
stdio protocol byte-for-byte, and runs an owner-private local attestation
socket. The native pre/post hooks query that socket for every task:

- the configured task ID receives the root guard;
- all other task IDs are explicitly classified as workers;
- an absent, corrupt, expired, or disarmed adapter denies hook dispatch inside
  this isolated host;
- the ordinary Desktop app remains unmodified and available for recovery.

The stdio proxy forwards each partial read immediately and flushes every frame.
It never waits for a 64 KiB buffer or input EOF, which is required because the
Desktop app-server pipe remains open for the life of the session.

The repository launcher invokes the actual Desktop executable directly and
places `--user-data-dir=<private instance>/electron-data` on its command line.
This happens before Electron's macOS single-instance decision; the environment
value alone is not treated as isolation proof. No owner-local wrapper or shim is
needed. Launch succeeds only after the exact recorded Desktop PID is observed
with that full switch and the exact proxy and real app-server PIDs are observed.

For the exact bound root task, the proxy adds Codex's supported per-tool
`approval_mode="approve"` setting to only these typed MCP controls: `doctor`,
`status`, bounded capacity reconfiguration, runtime verification,
`prepare-launch`, launch receipt, heartbeat, lifecycle watchdog, close/refill,
archive and refill receipts, slot status, watchdog refill, exact setup-failure
repair, typed owner-decision routing, missing-ticket archive reconciliation,
stale-present-ticket archive reconciliation, and one-use schema-hold recovery. It does not
change the user's global approval policy or plugin
configuration. The native hook denies that prompt-free set for every other task
ID in the isolated host. Expired-lease reconciliation remains outside the grant,
as do task creation itself and all shell, file, browser, Sites, credential,
destructive, owner-gated, production, and external tools.

Capacity reconfiguration additionally requires the verified runtime pin and
current covered-path adoption, an exact expected capacity and state revision,
and a bounded requested value. It cannot reduce below active/reserved
occupancy. The control transaction records one idempotency receipt and audit
event; the adapter and MCP server never edit SQLite directly.

This is still `COVERED_PATH_GUARDRAIL`, not universal enforcement. A worker can
share the same OS account, and hosted or specialized tools may bypass native
hooks. The live adoption test must continue to mark those paths uncovered.

## Safety gates

Before launch, `verify` requires all of the following:

1. the enabled plugin resolves to the exact local source reported by
   `codex plugin list`, that source and its exact versioned Codex cache have
   identical file contents and executable status, and all runtime files plus the
   real Codex CLI are regular non-symlink files with safe ownership and
   permissions;
2. the exact typed MCP registry is present;
3. direct `pm_proxy_doctor` and `pm_proxy_status` succeed against the intended
   owner-private state;
4. the current plugin's runtime pin verifies;
5. a real ephemeral Codex call attempts a synthetic marker write, the native
   hook returns `ROOT_ORCHESTRATOR_TASK_DOMAIN_DENIED:Bash`, and the marker is
   absent.

Doctor/status also inspect the latest dispatcher adoption. The prompt-free
grant is enabled only when that adoption is for the exact plugin version,
retains every covered-path/fence proof, and still states that hosted and
universal paths are uncovered. The exact tool list and adoption receipt are
then content-bound into the private proof and session. Missing, stale, or
non-current adoption does not receive a partial grant: the adapter can launch a
prompted bootstrap/canary host, but injects no approval overrides.

The resulting proof is content-bound and valid for 15 minutes. Launch repeats
the local checks and refuses a stale or mismatched proof. A host session expires
after 12 hours. A plugin, hook, adapter, CLI, runtime pin, or proof change
requires verification again.

The launch capability exists only in the isolated Desktop parent's environment.
The proxy validates it, then strips the capability, session path, real-CLI path,
Desktop override variables, and any inherited root role before starting the
real app-server. The real app-server receives only the attestation socket and a
non-secret instance ID.

## Operator workflow

Run these commands from an owner-controlled terminal, outside an enforced root
task. First install the complete `0.4.12` plugin, recreate the runtime pin for the
reviewed clean Firestarter runtime, and run doctor. Keep any global
`ROOT_ORCHESTRATOR_ROLE` export unset.

Choose a private adapter instance directory and the intended ORC state. Use the
adapter from either the exact local source path reported for the installed
plugin or its matching versioned Codex cache. Preflight rejects another
checkout, or a stale cache, with the same version string:

```bash
orc_adapter=/absolute/installed/pm-proxy-orchestrator/scripts/desktop_host_adapter.py
orc_instance="$HOME/.codex/orchestrator-hosts/primary-root"
orc_state="$HOME/.codex/orchestrator-state/intended-state"
codex_cli=/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex

"$orc_adapter" verify \
  --instance-dir "$orc_instance" \
  --state-dir "$orc_state" \
  --codex-cli "$codex_cli"
```

Within 15 minutes, bind one exact existing task ID and launch the isolated
Desktop host:

```bash
root_task_id=019f-example-root-task

"$orc_adapter" launch \
  --instance-id primary-root \
  --instance-dir "$orc_instance" \
  --root-thread-id "$root_task_id" \
  --state-dir "$orc_state" \
  --codex-cli "$codex_cli" \
  --desktop-executable /Applications/ChatGPT.app/Contents/MacOS/ChatGPT
```

Pass the CLI bundled inside the Desktop app (path above, current Desktop builds),
not a standalone `codex` from `PATH`: the isolated Desktop speaks the app-server
protocol of its own bundled CLI, and an older standalone CLI can fail Desktop's
startup policy read. Current Desktop builds also probe the selected CLI with a
bare `--version` before starting the app server; inside a valid armed host
session the adapter answers that probe from the recorded real CLI and refuses
every other non-app-server invocation.

Pass the real Desktop executable above, not a launcher shim. The adapter adds
the isolated `--user-data-dir` argument itself. The private session path and
capability token remain environment-only and are removed before the real
app-server starts; neither is placed on the Desktop command line.

Open or resume only the exact bound root task in that isolated window. Visible
worker tasks can run through the same host because their distinct task IDs are
attested as workers rather than inheriting the root role. Their ordinary
task-domain permissions are unchanged, but they cannot use the root's
prompt-free PM-proxy control surface.

An exceptional schema hold first requires the owner-operated
`issue-bootstrap-recovery-grant` command against a clean reviewed source whose
`origin/master` still equals the authorized base. The grant binds the exact
task, ticket, receipt, claim fence, state/policy revisions, configured capacity,
root/host instance, runtime/plugin digests, and typed decision for at most five
minutes. Relaunch the isolated host with `--bootstrap-grant` pointing to that
private file. The MCP route revokes it before dispatch and records one use even
when the hold call fails; it cannot authorize another tool or a second attempt.

Immediately run the disposable closed-path canary. Prove exact root denial and
zero side effect, one worker task-domain allowance, one reserved create with an
exact receipt, lifecycle debt and watchdog clearing, refill fencing, and exact
archive admission. Do not record adoption if any step fails. Do not claim
hosted, unattended, platform-wide, or universal coverage.

If this was the prompted bootstrap for a new plugin version, record adoption
through the owner-operated fixed bridge only after the canary passes. Then stop
that isolated host with its matching adapter, run `verify` again, and relaunch.
`verify`, `launch`, and `status` must report
`prompt_free_control_grant_verified=true` before the repeated typed MCP prompts
are considered fixed. Never edit the session or transplant an adoption receipt.

## Shared Codex tool configuration

The isolated host shares the ordinary `CODEX_HOME`, because it needs the same
plugin install, hook trust, sign-in and task history. Current Codex Desktop
builds write the tool environment they were started with into the
`[mcp_servers.node_repl.env]` table of the shared `config.toml`. The isolated
Desktop is started with this adapter as `CODEX_CLI_PATH`, so it writes the
adapter there, and because computer use is unavailable in its private profile it
can also drop the computer-use entries and add a disabled
`[mcp_servers.cua_repl]` table. Any ordinary Codex task that loads the shared
config in that state runs the adapter for its tools and is refused with
`only-foreground-app-server-is-allowed`.

The adapter therefore guards that one table. This is its only write to the
shared config, and it only undoes the isolated Desktop's own rewrite:

- `launch` records the table, with its sub-tables and any `cua_repl` table, in
  the private instance directory before the Desktop starts, and reports the
  guard as `shared_tool_config_guard`: `active`, or `inactive:<reason>` when it
  cannot protect the config (see the limits below).
- A relaunch of the same instance first restores from the record it already
  has and never replaces that record while the shared table still names the
  adapter, because the record is the only copy of the ordinary table.
- While a proxy lives it checks the shared config about once a second, backing
  off after each rewrite. Proxy exit, `stop`, and a launch that fails after the
  Desktop started check once more. `stop` reports `shared_tool_config_restored`,
  which is true only when it rewrote the file; false means either that nothing
  needed restoring or that the guard could not act.
- A restore happens only while the shared table still names the adapter as the
  Codex CLI (any copy of it, from the source checkout or a plugin cache), which
  shows an isolated Desktop was its last writer. It puts back
  the recorded table (or removes the table if none existed before), removes a
  disabled `cua_repl` table that was not there before, and copies the rest of
  the file through unchanged, line endings included. Nothing is written unless
  the result parses and differs from the current file only in those two tables,
  and the file is an ordinary file owned by the user.

Limits, stated plainly:

- The guard needs Python 3.11 or newer (`tomllib`), an absolute `CODEX_HOME`,
  and a `config.toml` that is an ordinary file (not a symlink) and parses. It
  also stays inactive if a guarded table holds anything but plain string
  settings, or is written in a form it does not read (an inline table, or a
  header line with a trailing comment). In each case `launch` reports
  `inactive:<reason>` and the operator must repair the table by hand after the
  host stops. An existing record is kept whenever the shared table still names
  an adapter, so it can still be used once the file is repaired.
- When an earlier host left the adapter path behind and no usable record
  exists, only the `CODEX_CLI_PATH` line can be repaired, using the CLI passed
  to `launch`. Anything else that earlier host removed stays removed, and a
  disabled `cua_repl` table is then removed even if it predates the host,
  because the adapter can no longer tell.
- The record belongs to one instance. If a second instance is launched while
  the first one's adapter path is still in the shared table, it takes the
  repair path above and the first instance's better record goes unused. Run
  one isolated host at a time.
- If the `cua_repl` table cannot be put back or removed cleanly, the adapter
  still takes itself out of the tool table and leaves `cua_repl` as it found
  it.
- Codex takes no lock on its config. The adapter checks that the file did not
  change while it prepared the restore, but a write by Codex that lands in the
  final instant before the rename can be lost.
- A comment placed inside the guarded table comes back as it was recorded.
- There is a window of about a second after the isolated Desktop writes the
  table, and longer (up to a minute) if the Desktop keeps rewriting it, because
  the check backs off after each rewrite. Codex keeps tool configuration per
  task in memory, so an ordinary task
  that loads its configuration inside that window keeps the adapter path for
  its lifetime. Start a new task to recover; restoring the file does not reach
  tasks that are already running.
- After a restore, tasks inside the isolated host also read the real CLI path
  for their tools. The proxy, the attestation socket and the root guard do not
  depend on that table.
- Keep the isolated host up only as long as the work needs, and avoid starting
  ordinary Codex tasks that need tools in the seconds after a launch.

## Status and recovery

Status reads only the private adapter session:

```bash
"$orc_adapter" status --instance-dir "$orc_instance"
```

The normal recovery path disarms first, signals only the exact recorded Desktop,
proxy, and real app-server PIDs after checking their commands. The Desktop PID
must match both the actual executable and the full private `--user-data-dir`
argument, so the ordinary Desktop process is not a candidate. Shutdown waits for
a bounded interval and never uses a process-name sweep or force kill:

```bash
"$orc_adapter" stop --instance-dir "$orc_instance"
```

If status remains `STOPPING`, close only the isolated ORC Desktop window. The
ordinary Desktop app was never reconfigured and remains the fallback. Retain
the private instance directory for inspection until the failed canary or host
shutdown is understood; removing it is a separate owner decision.

Version `0.3.6` session records use schema `1.2`. Stop an active `0.3.5` host
with its matching `0.3.5` adapter before replacing that installed source. A
rollback restores the prior complete plugin version, pin, and adoption proof;
it never copies a session token or edits an old session record into compatibility.
