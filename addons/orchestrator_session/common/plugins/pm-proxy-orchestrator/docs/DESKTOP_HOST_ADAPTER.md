# Codex Desktop host adapter

Version `0.3.4` includes an opt-in desktop host adapter for one exact root task.
It does not export `ROOT_ORCHESTRATOR_ROLE` to the normal desktop process and it
does not infer root identity from a prompt, working directory, project, or
model-visible field.

The owner supplies the exact existing root task ID. The adapter launches a
separate Electron data directory and acts as the CLI path selected by Codex
Desktop. It accepts only a foreground `app-server` invocation, proxies the
stdio protocol byte-for-byte, and runs an owner-private local attestation
socket. The native pre/post hooks query that socket for every task:

- the configured task ID receives the root guard;
- all other task IDs are explicitly classified as workers;
- an absent, corrupt, expired, or disarmed adapter denies hook dispatch inside
  this isolated host;
- the ordinary Desktop app remains unmodified and available for recovery.

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
3. direct `pm_proxy_doctor` succeeds against the intended owner-private state;
4. the current plugin's runtime pin verifies;
5. a real ephemeral Codex call attempts a synthetic marker write, the native
   hook returns `ROOT_ORCHESTRATOR_TASK_DOMAIN_DENIED:Bash`, and the marker is
   absent.

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
task. First install the complete `0.3.4` plugin, recreate the runtime pin for the
reviewed clean Firestarter runtime, and run doctor. Keep any global
`ROOT_ORCHESTRATOR_ROLE` export unset.

Choose a private adapter instance directory and the intended ORC state. Use the
adapter from either the exact local source path reported for the installed
plugin or its matching versioned Codex cache. Preflight rejects another
checkout—or a stale cache—with the same version string:

```bash
orc_adapter=/absolute/installed/pm-proxy-orchestrator/scripts/desktop_host_adapter.py
orc_instance="$HOME/.codex/orchestrator-hosts/primary-root"
orc_state="$HOME/.codex/orchestrator-state/intended-state"
codex_cli=/Applications/ChatGPT.app/Contents/Resources/codex

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

Open or resume only the exact bound root task in that isolated window. Visible
worker tasks can run through the same host because their distinct task IDs are
attested as workers rather than inheriting the root role.

Immediately run the disposable closed-path canary. Prove exact root denial and
zero side effect, one worker task-domain allowance, one reserved create with an
exact receipt, lifecycle debt and watchdog clearing, refill fencing, and exact
archive admission. Do not record adoption if any step fails. Do not claim
hosted, unattended, platform-wide, or universal coverage.

## Status and recovery

Status reads only the private adapter session:

```bash
"$orc_adapter" status --instance-dir "$orc_instance"
```

The normal recovery path disarms first, signals only the exact recorded Desktop,
proxy, and real app-server PIDs after checking their commands, waits for a
bounded interval, and never uses a process-name sweep or force kill:

```bash
"$orc_adapter" stop --instance-dir "$orc_instance"
```

If status remains `STOPPING`, close only the isolated ORC Desktop window. The
ordinary Desktop app was never reconfigured and remains the fallback. Retain
the private instance directory for inspection until the failed canary or host
shutdown is understood; removing it is a separate owner decision.
