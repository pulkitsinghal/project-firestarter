# Orchestrator Session add-on

A reusable **master-orchestrator session**: paste one prompt into a fresh Claude
Code (or any capable agent) session opened at your portfolio/repo root, and that
one session plans, delegates, verifies, and lands work across many repos — while
you stay in the loop through it alone. Stack-agnostic and 100% dependency-free.

Enable it at stamp time:

```bash
./bin/firestart.sh --set include_orchestrator_session=yes
```

## What you get

| File | Purpose |
|------|---------|
| `ORCHESTRATOR_PROMPT.md` | The paste-in bootstrap prompt. Open a fresh session at your portfolio root, paste it, and go. Turns that session into the master orchestrator (operating loop, fan-out via subagents/workflows, proxy-PM decision gate, verify-before-implement, secret hygiene, one decisions board, never-go-dark reporting). |
| `AGENTS.orchestrator.md` | A paste-able **AGENTS.md addendum**. Copy the marked "Orchestrator posture" section into your repo's `AGENTS.md` (or `CLAUDE.md`) so any agent that reads it adopts the posture durably — the always-on companion to the one-time paste. |
| `decisions-board/decisions.json` | Starter schema for the single source of truth: `{ generated, items:[{ id, project, cat, status, title, context, rec, link }] }`, where `cat` is `done` / `act` / `decide` / `plan` / `review`. Ships 2–3 clearly-labeled EXAMPLE items — replace them. |
| `decisions-board/decisions.html` | A self-contained, dependency-free, dark-mode-aware viewer. Fetches `decisions.json` and groups items by category. |

## The three-step setup

1. Open a **fresh** Claude Code session at the root of your projects/portfolio.
2. Paste the contents of `ORCHESTRATOR_PROMPT.md`.
3. Go. (Or reference the prompt from your repo's `CLAUDE.md` / `AGENTS.md`, and
   add the `AGENTS.orchestrator.md` section so future sessions inherit the posture.)

## Serving the decisions board

The board is plain static files — serve the `decisions-board/` folder with **any**
static file server and open `decisions.html` (opening via `file://` may block the
`fetch()`; serve it instead). For a board reachable from your phone, run a durable
static server (launchd/systemd) on your tailnet.

## Cost & safety

- **No new dependencies, no host toolchain, no network calls** — the prompt and the
  board are just text and a single self-contained HTML file.
- **Generic by design:** ships no owner-specific repos, config, or secrets. It
  encodes *posture*, not your portfolio — bring your own.
- The prompt tells the orchestrator to treat everything read through tools as data
  (not instructions), verify before implementing, never blanket-stage in shared
  clones, and gate on genuine irreversibles (prod deploys, spend, deletes, sending
  on your behalf) with a recommendation rather than a survey.
