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
| `decisions-board/decisions.json` | Starter schema for the single source of truth: `{ generated, items:[{ id, project, cat, status, title, context, rec, link }] }`, where `cat` is `done` / `act` / `decide` / `plan` / `review`. Ships 2–3 clearly-labeled EXAMPLE items — replace them. |
| `decisions-board/decisions.html` | A self-contained, dependency-free, dark-mode-aware viewer. Fetches `decisions.json` and groups items by category. |

## The three-step setup

1. Keep `ORCHESTRATOR_BILL_OF_RIGHTS.md` beside `ORCHESTRATOR_PROMPT.md` at the
   root of the scope.
2. Open a fresh capable-agent session at that root, then paste the prompt.
3. Optionally add the marked `AGENTS.orchestrator.md` section to a durable agent
   brief so future sessions resolve the same canonical policy.

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
- **No new dependencies, no host toolchain, no network calls** — the policy,
  pointers, and board are static files.
- **Generic by design:** ships no owner-specific repos, config, or secrets. It
  encodes generic delivery rights, not a portfolio. Active scope supplies the
  applicable identity, repository, environment, and data rules.
