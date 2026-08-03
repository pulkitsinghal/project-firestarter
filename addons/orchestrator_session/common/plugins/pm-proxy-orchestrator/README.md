# PM Proxy Orchestrator

Version `0.3.4` is a source-only agent-CLI plugin for Firestarter control-plane
interface `1.0`. It makes task reservation, policy receipts, approval routing,
fenced handback, successor creation, and queue recycling operational without
installing anything globally.

The plugin does not bundle or replace Firestarter's SQLite authority. Configure
an absolute path to the compatible `orchestrator_control.py` and an initialized
private state directory at use time. See `docs/OPERATIONS.md` and
`docs/INSTALL_UPDATE_ROLLBACK.md`.

Schema `1.2` adds duration controls and a root-role guard adapter. The package
also bundles supported `PreToolUse` and `PostToolUse` hooks with status
`COVERED_PATH_GUARDRAIL`. A trusted project hook can deny covered task-domain
calls before dispatch, require a fresh exact Firestarter ticket for task
creation, fence archive behind a satisfied refill saga, and require a successful
lifecycle-watchdog call after each covered read/wait before another status or
lifecycle action. Hosted paths, opt-outs, reauthorization gaps, and universal
non-spoofable caller identity remain unresolved. See
`docs/DISPATCHER_ENFORCEMENT.md`.

Version `0.3.4` also includes an opt-in Desktop app-server proxy. An
owner-selected exact task ID is attested as root through a private local socket;
other task IDs remain workers, so visible workers do not inherit a process-wide
root role. The adapter requires current pin/doctor state and a fresh native-hook
marker-denial proof, launches with an isolated Electron data directory, changes
no global Codex configuration, and keeps the normal Desktop app as the recovery
path. See `docs/DESKTOP_HOST_ADAPTER.md`.

Bridge/ticket `1.3` accepts control schema `1.3`, requires the exact root and
worker runtime policy plus a truthful launch attestation before receipt, and
adds lifecycle-watchdog reconciliation. A desktop-app priority tier is
`config-verified` because its task/thread and spawn APIs do not report service
tier; only a genuinely surfaced platform tier is `runtime`. Root never creates
internal subagents: workers are visible peer tasks, root is excluded from worker
capacity, and closure follows handback → release → blocked re-audit → successor
receipt or terminal proof → archive.

An exact one-for-one closure replacement preserves the predecessor's
receipt-backed occupancy even when the pool was already under configured
capacity. The selected successor must still be reserved in the same SQLite
transaction and receipted before predecessor archive; unrelated idle slots stay
visible and do not turn that already-reserved successor back into runnable work.

The plugin includes a local stdio MCP server exposing only typed verifier,
doctor, reserve/receipt, lifecycle, close/refill, status, and archive-receipt
operations. It has no network client, app connector, shell executor, generic
filesystem tool, or arbitrary-command field.

An owner-operated runtime pin binds that MCP surface to one exact Firestarter
worktree and a content digest covering the control CLI, version, schemas,
root-role guard, and runtime verifier. Bootstrap doctor/status and exact
expired-lease repair remain available before pinning, but launch and refill
operations fail closed until both the private runtime pin and a matching live
covered-path dispatcher-adoption receipt exist. A pin mismatch or later source
drift is denied before the control CLI runs.

Dispatcher adoption is operator-only through the fixed bridge command and is
not exposed by the MCP server. This prevents an orchestrator from turning
caller-supplied proof flags into its own automatic-control authorization.
Readiness is bounded to covered paths; unattended and universal enforcement
remain explicitly false.

The typed `pm_proxy_reconcile_expired_lease` operation retires only the exact
receipt-fenced owner after its stored lease deadline. It advances the task to a
tombstone fence, marks the claim expired, and releases logical capacity without
takeover, handback, closure, archive, successor creation, or refill. Status can
accept an explicit UTC clock so stale and expired evidence is never inferred
from an unknown evaluation time.

The plugin manifest explicitly binds `mcpServers` to `./.mcp.json`. This is a
safety invariant, not packaging metadata: Codex can discover the default
`hooks/hooks.json` independently, while a bundled MCP server must be declared by
the manifest. The Firestarter overlay therefore never stamps a project-level
`.codex/hooks.json` or assigns the trusted root role. Install the complete
plugin, verify the required `pm_proxy_*` tools in a hook-untrusted bootstrap
task, and only then trust the exact hook and perform covered-path adoption. See
`docs/INSTALL_UPDATE_ROLLBACK.md` for partial-activation recovery.
