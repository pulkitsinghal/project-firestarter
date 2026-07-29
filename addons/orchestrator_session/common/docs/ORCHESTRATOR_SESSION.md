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
| `ORCHESTRATOR_BILL_OF_RIGHTS.md` | The canonical policy: precedence and bounded conversation-derived training, PM-proxy ownership, launch envelopes, routine autonomy, exceptional gates, canonical repo/path ownership, duplicate-stop and blocked-queue re-audit behavior, delivery evidence, CI truth, closure/successor transactions, cleanup, privacy, identity, and reporting. |
| `ORCHESTRATOR_PROMPT.md` | Thin paste-in bootstrap pointer to the Bill plus the initial inventory instruction. |
| `AGENTS.orchestrator.md` | Thin paste-able `AGENTS.md` addendum that makes the Bill the durable policy source. |
| `orchestrator-control/` | Versioned generic policy ledger, local SQLite authority, stable JSON CLI, schemas, security-hardened dashboard, and Phase-2 skill/plugin wrapper contract. |
| `decisions-board/decisions.json` | Legacy-compatible starter display data. It is a view, not task or approval authority. |
| `decisions-board/decisions.html` | A self-contained dark-mode-aware compatibility viewer with CSP and an HTTP(S)-only link allowlist. |

## The three-step setup

1. Keep `ORCHESTRATOR_BILL_OF_RIGHTS.md` beside `ORCHESTRATOR_PROMPT.md` at the
   root of the scope.
2. Open a fresh capable-agent session at that root, then paste the prompt.
3. Optionally add the marked `AGENTS.orchestrator.md` section to a durable agent
   brief so future sessions resolve the same canonical policy.

For enforced task creation, initialize the private local authority and require
the Phase-2 wrapper flow:

```bash
python orchestrator-control/orchestrator_control.py \
  --state-dir /absolute/private/state init \
  --now 2026-07-28T18:00:00Z
```

The wrapper must call `prepare-launch` before `create_thread`, append the
returned envelope to the ephemeral prompt, and record the launch receipt before
the worker mutates anything. All approval questions route through
`classify-decision`; closure uses `record-handback`; capacity and startup
reconciliation use `recycle-queue`. See
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
  from policy or handback data.
- **Generic by design:** ships no owner-specific repos, config, or secrets. It
  encodes generic delivery rights, not a portfolio. Active scope supplies the
  applicable identity, repository, environment, and data rules.
