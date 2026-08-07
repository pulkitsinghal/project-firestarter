# PM Proxy Orchestrator

Version `0.4.10` is a source-only agent-CLI plugin for Firestarter control-plane
interface `1.0` and control bundle `1.4.9`. It makes typed configured-capacity
compare-and-set, task reservation, policy receipts, approval routing, fenced
handback, successor creation, and queue recycling operational without installing
anything globally.

Version `0.4.10` adds a generic legacy archive-reconciliation route for an exact
terminal task whose claim is released and archive outbox remains pending after
the external task was independently proved archived or unavailable, but its old
transport ticket is missing. Exact identity, state revision, fence, claim,
outbox, external proof, and a bounded ticket scan are required; every mismatch
fails closed. Capacity failure now reports only the newest actionable invariant
state while preserving every historical audit row.

Version `0.4.9` closes the final terminal archive gap. The control transaction
accepts a receipted successor that has itself completed only when its launch
receipt, released claim, completed lifecycle, and pending or completed archive
outbox all match. The bridge admits an expired ordinary `completed` predecessor
only when the exact committed terminal handback, released claim, terminal refill
outcome, canonical receipt fence, and archive outbox agree; stale, partial, or
mismatched records remain denied.

Version `0.4.8` gives lifecycle observations a closed identity classifier. A
thread is typed as the pinned owner-decision sink, one exact receipt-backed task,
unknown, mismatched, or unverifiable before the hook records worker debt. The
sink is excluded only when a bounded read-only scan proves no task receipt uses
that identity. The same proof removes an exact legacy sink entry idempotently;
real, incomplete, unknown, duplicate, mismatched, and unverifiable identities
remain blocked.

Version `0.4.7` completes the archive-admission repair after an exact local-only or
local-artifact completion outlives its worker lease. The bridge requires the
matching canonical thread, ticket, policy/lease/fence identity, durable terminal
handback, released claim, archive-permitting refill outcome, and pending archive
outbox. When a reserved successor setup-failed atomically, it accepts only the
same authoritative saga's exact receipted replacement, including a replacement
that has since closed with a released claim and terminal archive receipt. A
separate current capacity deficit does not erase that historical receipt. No
lease, task label, claim, capacity, or successor is created or changed by
admission.

An expired predecessor marked `superseded` is admissible only when that same
authoritative failed-reservation replacement proof succeeds. The disposition
alone never authorizes archive.

Version `0.4.4` gives the control `1.4.3` legacy hold-table migration and its
operator documentation a distinct package identity. This keeps source/cache
parity, runtime pins, and dispatcher-adoption receipts unambiguous without
overwriting the earlier `0.4.3` artifact.

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

Version `0.4.8` also includes an opt-in Desktop app-server proxy. An
owner-selected exact task ID is attested as root through a private local socket;
other task IDs remain workers, so visible workers do not inherit a process-wide
root role. The adapter requires current pin/doctor state and a fresh native-hook
marker-denial proof. The repository launcher passes its private Electron data
directory on Desktop's command line before macOS single-instance selection,
observes that exact switch with the adapter proxy, changes no global Codex
configuration, and keeps the normal Desktop app as the recovery path. See
`docs/DESKTOP_HOST_ADAPTER.md`.

The patch adds two truthful local closure dispositions, an exact receipt-fenced
schema hold, and one expired-unreceipted setup-failure route. Owner-only
questions are classified from the receipt-backed source worker and emitted as a
closed typed envelope for the pinned private sink; PM-proxy questions return to
the worker immediately. The route consumes no worker slot, gives the sink no
authority, and persists no prompt, command, hash, credential, private text, or
credential-bearing URL. The hold is the only operation eligible for the
short-lived bootstrap recovery grant, which is revoked before dispatch and is
single-use under concurrent calls.

After the exact current-version covered-path adoption and runtime pin verify,
that isolated proxy also applies Codex's supported prompt-free mode to only the
named typed ORC control-plane mechanics. The setting is process-local and
per-tool, not a global approval-policy change. Exact-task attestation admits the
root while the hook denies the prompt-free set to other task IDs. The bounded
`pm_proxy_configure_capacity` operation requires both the expected state revision
and expected current capacity, enforces the active/reserved floor, and has no
launch side effect; task-domain, owner-gated, expired-lease reconciliation, and
universal paths are not widened.

Schema `1.4` adds owner-operated single-leader federation. The fixed
`scripts/federation_transfer.py` coordinator accepts only private source/target
state and disarmed source-host records. It stages exact transfer receipts,
demotes every old root before activating the successor, and then enables each
old ledger as a subordinate worker-capacity shard. Two four-lane shards therefore
provide federated capacity eight without changing either shard to eight. The
federation root's own ledger refuses worker launches, and no authority-transfer
command is exposed through MCP, so an ORC cannot adopt or promote itself.

Bridge/ticket `1.3` accepts control schema `1.4`, requires the exact root and
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
doctor, configured-capacity, reserve/receipt, lifecycle, close/refill, status,
archive-receipt, and legacy archive-reconciliation operations. It has no network client, app connector, shell
executor, generic filesystem tool, or arbitrary-command field.

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
