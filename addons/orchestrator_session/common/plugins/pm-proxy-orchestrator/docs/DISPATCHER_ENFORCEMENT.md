# Covered-path dispatcher guardrail

Status: `COVERED_PATH_GUARDRAIL`.

The plugin bundles supported catch-all `PreToolUse` and `PostToolUse` hooks.
When the plugin is installed and the exact project hook is trusted and active,
the root receives a fixed trusted-project role assignment. The hooks deny
covered task-domain calls before dispatch: Bash/unified exec, `apply_patch`,
Agent/spawn, non-control MCP calls, and most local function paths.

The allowed local MCP namespace contains only typed Firestarter operations and
has no generic exec/filesystem/network capability. Covered `create_thread`
requires one fresh exact unreceipted ticket whose launch envelope matches the
verbatim prompt; replay under a different tool-use ID is denied. Covered archive
requires the exact receipted predecessor, terminal handback, and a refill ledger
outcome of `REFILL_SATISFIED`, `EMPTY`, `OWNER_GATED`, or `CAPACITY_FULL`.

Before a covered `read_thread` or `wait_threads` dispatches, the PreToolUse hook
durably records a per-session lifecycle intent; the PostToolUse hook confirms
that debt after the observation. If the intent cannot be recorded, the
observation is denied. The guard then denies another read/wait, create, archive,
status, or watchdog-refill until the typed lifecycle-watchdog call succeeds for
each exact observed worker and the PostToolUse hook clears the debt.

Both hook ledgers use owner-only regular lock files and bounded nonblocking lock
acquisition well inside the five-second hook deadline. Lock contention denies
quickly with a typed reason instead of hanging the dispatcher. Admission
records are retained only while their exact create ticket or pre-archive fence
is live, so stale terminal records are pruned before the 512-entry safety cap;
an archive receipt makes that ticket ineligible for any later archive admission.

This is not universal root-role enforcement:

- hosted tools may not traverse the hook;
- specialized tools may opt out;
- `write_stdin` does not reauthorize a command already admitted;
- untrusted or disabled non-managed plugin hooks do not enforce;
- the documented hook payload has no non-spoofable root/worker identity, and
  subagents share the parent `session_id`.

The source tests prove classifier denial, one-shot launch admission, stale
admission pruning, bounded lock-contention denial, pre-dispatch lifecycle
intent/debt clearing, terminal archive rejection, private typed MCP operation,
and zero calls in synthetic dispatchers. Live runtime proof must still be
repeated after installation and trust because source validation does not prove
platform hook coverage.

On a complete live proof, an owner-operated process outside root-role execution
can record a bounded dispatcher-adoption receipt through the fixed bridge
command. The MCP surface deliberately cannot write this receipt, so the
orchestrator cannot approve caller-supplied proof flags for itself. Status then
reports `covered_path_dispatcher_enforcement: true` and retains
`platform_dispatcher_enforcement: false`. The receipt explicitly records hosted
paths as uncovered and rejects any universal-coverage claim.

Version `0.3.3` also requires an owner-private content pin of the exact
Firestarter runtime. Automatic launch/refill readiness is true only when the pin
verifies and the newest
adoption receipt carries the current plugin version. A source update therefore
returns readiness to `DISABLED` until the runtime is repinned and the live proof
is repeated; an older adoption cannot authorize a newer dispatcher.

## Activation invariant

Codex discovers the default plugin hook at `hooks/hooks.json`, but the bundled
MCP server is part of the plugin only when `.codex-plugin/plugin.json` explicitly
points `mcpServers` at `./.mcp.json`. Keep those components paired. The source
scan and Firestarter stamping contract must fail if the pointer, exact bounded
server definition, or either component is missing.

The orchestrator-session overlay must not stamp `.codex/hooks.json`, assign
`ROOT_ORCHESTRATOR_ROLE=trusted-project-hook`, or otherwise arm root enforcement.
Activation is deliberately two phase:

1. Install the complete versioned plugin and start a new bootstrap task while
   its non-managed hook is still untrusted.
2. Confirm that the installed plugin exposes the exact required `pm_proxy_*`
   tools, pin the intended clean Firestarter runtime, and verify typed `doctor`
   succeeds against the intended private state without a caller-selected root.
3. Only then trust the exact current hook and let an adopting managed wrapper
   assign the root role in a new disposable task.
4. Complete the live denial, reserved-create, receipt, lifecycle, refill, and
   archive proof, leave root-role execution, and have the owner record
   covered-path adoption through the fixed bridge command.

A firing root guard with no callable `pm_proxy_*` tools is
`PARTIAL_ACTIVATION`, not enforcement. Restore the prior project hook state (or
no project hook) from outside the blocked task, restart Codex, and repair the
plugin install before trying again. Do not weaken the guard or use a denied Bash
bridge as a root fallback.

## Required live adoption test

In a disposable synthetic project:

1. Install the exact hashed plugin from the repo/team marketplace and trust the
   hook, or use an equivalent managed hook.
2. Start a new task and verify the active `PreToolUse` source/matcher.
3. Attempt synthetic canary mutations through exec, patch, non-control MCP/app,
   browser, Sites, task/thread, and Agent paths.
4. For each claimed-covered path, prove the hook fired before dispatch, denial
   was returned, downstream invocation count stayed zero, and no side effect
   exists.
5. Record hosted-tool and specialized-tool escape tests as uncovered, not pass.
6. Verify one valid reserved create is admitted once, its receipt is recorded,
   a covered wait creates lifecycle debt, a successful watchdog clears it, and
   archive remains denied until the exact refill saga permits it.
7. Repeat after agent-CLI/plugin upgrades.

Do not infer role from cwd, prompt text, transcript, `session_id`, or a
caller-controlled environment variable. Until the platform supplies trusted
caller identity and universal coverage, retain the status label above.
