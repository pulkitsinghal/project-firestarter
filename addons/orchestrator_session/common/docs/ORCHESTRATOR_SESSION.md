# Orchestrator Session add-on

A reusable, stack-agnostic master-orchestrator session with one authoritative
policy: [`ORCHESTRATOR_BILL_OF_RIGHTS.md`](../ORCHESTRATOR_BILL_OF_RIGHTS.md).
The bootstrap and agent addendum point to the Bill instead of maintaining
shorter policy copies that can drift.

Enable it at stamp time:

```bash
./bin/firestart.sh --set include_orchestrator_session=yes
```

## What you get

| File | Purpose |
|------|---------|
| `ORCHESTRATOR_BILL_OF_RIGHTS.md` | The canonical policy: precedence and bounded conversation-derived training, PM-proxy ownership, the mandatory root-role boundary, launch envelopes, routine autonomy, exceptional gates, canonical repo/path ownership, duplicate-stop and blocked-queue re-audit behavior, delivery evidence, CI truth, closure/successor transactions, cleanup, privacy, identity, and reporting. |
| `ORCHESTRATOR_PROMPT.md` | Thin paste-in bootstrap pointer to the Bill plus the initial inventory instruction. |
| `AGENTS.orchestrator.md` | Thin paste-able `AGENTS.md` addendum that makes the Bill the durable policy source. |
| `orchestrator-control/` | Versioned generic policy ledger, schema-1.3 local SQLite authority, mandatory `root_role_guard.py`, evidence-derived lifecycle watchdog, duration-calibrated worker lanes, stable JSON CLI, schemas, security-hardened dashboard, and Phase-2 skill/plugin wrapper contract. |
| `.agents/plugins/marketplace.json` | Repo-local marketplace entry for the validated `pm-proxy-orchestrator` source plugin; it is not a personal installation. |
| `plugins/pm-proxy-orchestrator/` | Operational bridge, skill, closure/refill saga, docs, synthetic task-tool stub, and deterministic privacy/adversarial/race tests. |
| `decisions-board/decisions.json` | Legacy-compatible starter display data. It is a view, not task or approval authority. |
| `decisions-board/decisions.html` | A self-contained dark-mode-aware compatibility viewer with CSP and an HTTP(S)-only link allowlist. |

## The three-step setup

1. Keep `ORCHESTRATOR_BILL_OF_RIGHTS.md` beside `ORCHESTRATOR_PROMPT.md` at the
   root of the scope.
2. Open a fresh capable-agent session at that root, then paste the prompt.
3. Optionally add the marked `AGENTS.orchestrator.md` section to a durable agent
   brief so future sessions resolve the same canonical policy.

## Startup runbook

Before the root coordinates any task:

1. Start from the exact project root and require that exact path to be
   `trusted` in the machine-local Codex config. The checked-in
   `.codex/config.toml` and machine config must both resolve to root and spawn
   defaults `gpt-5.6-sol`, `xhigh`, and `service_tier = "fast"`, with
   `fast_mode` and `multi_agent` enabled.
2. Capture a bounded launch attestation for the effective root model, reasoning
   effort, fast mode, authentication mode, and service-tier provenance. Model
   and effort values must come from the launch/runtime surface. Use
   `service_tier_attestation: "runtime"` with
   `tier_provenance: "platform-runtime"` only when the platform genuinely
   reports the effective tier.
3. ChatGPT desktop task/thread and spawn APIs do not report service tier. For
   that surface, use `service_tier_attestation: "config-verified"` with
   `tier_provenance: "trusted-project-and-user-config"` only after both exact
   configs and project trust verify. Never relabel config-derived evidence as
   runtime. API-key authentication, an unattested tier, an untrusted project,
   or any project/user/launch override drift fails closed.
4. Run the read-only verifier before initializing the authority:

   ```bash
   python bin/verify-orchestrator-runtime.py \
     --project-root "$PWD" \
     --runtime-attestation /absolute/ephemeral/launch-attestation.json
   ```

   Continue only when it returns `ok: true`. The verifier does not edit the
   machine config. Remove the ephemeral attestation through task-owned cleanup.
5. Root remains coordination-only, never spawns an internal subagent, and
   creates workers only as visible peer tasks. Root is excluded from worker
   capacity. On closure, preserve the exact sequence: handback, atomic capacity
   release, blocked-work re-audit, successor receipt or terminal-empty proof,
   then predecessor archive.

For enforced task creation, initialize the private local authority and require
the Phase-2 wrapper flow:

```bash
python orchestrator-control/orchestrator_control.py \
  --state-dir /absolute/private/state init \
  --now 2026-07-28T18:00:00Z
```

Before every root tool call or action, the wrapper must evaluate
`root_role_guard.py`. Root is limited to owner-intent intake, visible-task
reserve/prepare/launch, ownership deduplication, PM-proxy routing,
receipt/handback monitoring, receipt-backed capacity refill, and synthesis from
worker evidence. Repository inspection, design, code, tests, estimation,
deployment, and cleanup go to a worker lane. `assigned` and `running` derive
from receipts/heartbeats; `validated`, `merged`, and `deployed` require matching
worker handback evidence. This is a control-plane invariant, not prompt
etiquette: eligible worker capacity makes root coordination-only, and
PM-proxy-safe refill means the root is not blocked. The current guard allows no
unreceipted direct execution. Its only exception is an exact, scope/action-bound
`ROOT_EXECUTION_EXCEPTION` for nondelegable recovery with zero eligible workers,
`SYSTEM_NONDELEGABLE_RECOVERY` authority, and a lifetime of at most 300 seconds.

The checked-in guard is a source artifact, not a dispatcher. Runtime enforcement
is voluntary until the active application/platform wrapper invokes it before
every filesystem, execution, browser, Sites, and task-management tool and
suppresses the underlying call on denial. Report merged exact-master source
validation, repo/team adoption or installation, and real dispatcher-denial E2E
as three distinct evidence stages. Active worker counts exclude root and queued
setup; queued setup may count only in the separately visible reserved
component. Owner notification requires a current typed `OWNER_GATE`; dashboard
status names its receipt/handback source and whether it is fresh or stale.

An adopting dispatcher must invoke `lifecycle-watchdog` after every worker
message, wait timeout, and before every status claim; this source package does
not interpose on those platform events itself. Objective
tests/output/closure evidence is retained separately as
`COMPLETION_CANDIDATE`; a `running` label is not authority. Fresh explicit
remaining-work progress may defer handback, but two missed checks default to
`TERMINALIZE`/`INTERRUPT_REQUIRED`. An exact interrupt receipt then performs
the same fenced release, blocked re-audit, successor reservation or evidenced
terminal-empty outcome, and archive sequence as a clean handback.

Every launch envelope includes an active-runtime estimate in one fixed lane:
`seconds` (0–<60s), `5m` (60–<450s), `10m` (450–<750s), `15m`
(750–<1,050s), `20m` (1,050–<1,500s), `30m` (1,500–<2,250s), `45m`
(2,250–<3,150s), or `60m+` (≥3,150s). `blocked` and `waiting` are
non-runtime states. The receipt carries its monotonic estimate version,
confidence, coarse task/tool/environment families, bounded evidence, expected
setup/test/remote-wait components, and heavyweight cap.

Progress records active work separately from queue, setup, tool wait, external
wait, total wall, first useful evidence, and safe close. Crossing the next
boundary, a >2x underestimate, or a two-bucket skip reclassifies the same fenced
worker without restart or ownership loss and can refill the released shorter
lane. Early finish contributes shorter evidence. Learned automatic priors need
at least five consistent completed samples for the exact coarse family/tool/
environment tuple; unknown timing remains `null`, and sparse or conflicting
evidence stays low-confidence. Queue aging protects short work from starvation,
`45m`/`60m+` concurrency is capped, queued setup is reserved-not-active, and
failed setup must roll back and immediately select the next eligible candidate.

The verified seed aggregate has SHA-256
`c3739bb1abff972ba6a85ecacfd9b794c6843d972b2ff90320b7eef67030585a`.
Its four completed observations across three families and four censored
snapshots are below the learned-prior threshold. Duration state retains no raw
prompt/hash, source task/thread identifier, title, path, URL, email, PHI/private
content, secret, command, diff, or command output.

The wrapper must call `prepare-launch` before `create_thread`, append the
returned envelope to the ephemeral prompt, and record the launch receipt before
the worker mutates anything. All approval questions route through
`classify-decision`; closure uses `record-handback`; capacity and startup
reconciliation use `recycle-queue` plus the event-driven
`capacity-watchdog` fallback. Predecessor archival is fenced until the selected
successor has a fresh exact launch receipt or an evidenced terminal empty
outcome. See
[`orchestrator-control/docs/PHASE2_PLUGIN_INTEGRATION.md`](../orchestrator-control/docs/PHASE2_PLUGIN_INTEGRATION.md).

## Serving the decisions board

The board is plain static files — serve the `decisions-board/` folder with **any**
static file server and open `decisions.html` (opening via `file://` may block the
`fetch()`; serve it instead). For a board reachable from your phone, run a durable
static server (launchd/systemd) on your tailnet.

## Contract and safety

- **One policy source:** change orchestrator policy in the Bill. Keep the prompt
  and agent addendum as pointers.
- **Stamp contract:** Firestarter's stdlib contract test enables this add-on for
  every declared stack and byte-compares each stamped Bill to the canonical
  source. It also pins the explicit failure-prevention clauses.
- **Local-only stdlib enforcement:** the control plane uses Python stdlib and
  SQLite, makes no network calls, stores no raw prompt, and executes no commands
  from policy or handback data. The root guard retains only bounded redacted
  classification metadata and fails closed if its audit state is corrupt.
  Duration calibration stores only coarse labels, bounded timings, and redacted
  evidence references; unknown measurements remain null.
- **Generic by design:** ships no owner-specific repos, config, or secrets. It
  encodes generic delivery rights, not a portfolio. Active scope supplies the
  applicable identity, repository, environment, and data rules.
