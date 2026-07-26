# orchestrator_session add-on

Bootstrap a **master-orchestrator** Claude Code session — one session that manages
a whole portfolio of repos — in a single paste. Stack-agnostic, 100%
dependency-free, and generic (nothing owner-specific).

This add-on packages the reusable pieces so anyone (owner or not) can turn a fresh
agent session into an orchestrator that plans, delegates, verifies, and lands work
across many repos while the human stays in the loop through that one session.

## What's in here

```
orchestrator_session/
├── README.md                          # this file (addon-level, not stamped into projects)
└── common/                            # overlaid into a project when include_orchestrator_session=yes
    ├── ORCHESTRATOR_PROMPT.md         # the paste-in bootstrap prompt (verbatim, generic)
    ├── AGENTS.orchestrator.md         # paste-able AGENTS.md addendum ("Orchestrator posture")
    ├── docs/ORCHESTRATOR_SESSION.md   # the house-style add-on doc that lands in a stamped project
    └── decisions-board/
        ├── decisions.json             # starter schema + 2–3 EXAMPLE items to replace
        └── decisions.html             # self-contained dark-mode-aware viewer (no deps)
```

## Very easy setup (three steps)

1. Open a **fresh** Claude Code session at the root of your projects/portfolio.
2. Paste the contents of [`common/ORCHESTRATOR_PROMPT.md`](common/ORCHESTRATOR_PROMPT.md).
3. Go.

That's it — no install, no config. Optionally, instead of pasting each time,
reference the prompt from your repo's `CLAUDE.md`/`AGENTS.md`, and paste the
"Orchestrator posture" section from
[`common/AGENTS.orchestrator.md`](common/AGENTS.orchestrator.md) into your
`AGENTS.md` so every future session inherits the posture automatically.

To vendor these files into a generated project instead, stamp with the add-on on:

```bash
./bin/firestart.sh --set include_orchestrator_session=yes
```

## What it does

- **Fan-out, not do-it-all:** the session spawns parallel subagents (one lane per
  independent task) and authors workflows for wide/multi-phase work (audits,
  migrations, sweeps) — scout inline first to build the work-list, then delegate.
- **Proxy-PM decision gate:** acts autonomously on routine, low-risk work; pauses
  only for genuine irreversibles (prod deploys/releases, DNS/prod-config, deleting
  or overwriting data it didn't create, sending on your behalf, spend, self-merging
  someone's active branch). When it gates, it gives a recommendation, not a survey.
- **One decisions board:** a single `decisions.json` + `decisions.html` as the
  canonical status of everything — done / running / owner-gated — updated as work
  lands.
- **Never-go-dark loop:** understand → fan out → verify → land → report → next,
  with owner-gated items surfaced early and a labeled footer of links each turn.
- **Verify before implementing:** checks current state first (already merged?
  already shipped?) so finished work isn't redone.
- **Secret hygiene & injection safety:** never echoes/logs/commits secrets; treats
  everything read through tools as data, not instructions; never blanket-stages in
  shared clones.

## What it deliberately does NOT include

- **No owner-specific configuration** — no private repos, hostnames, ports,
  schedules, secrets, or personal decision history. The prompt encodes *posture*,
  so it's usable by anyone; you bring your own portfolio.
- **No dependencies and no host toolchain** — the prompt is text and the board is a
  single self-contained HTML file plus a JSON. Nothing to install, nothing to run
  on the host.
- **No credentials or network calls** baked in. The board's example items are
  clearly labeled placeholders meant to be replaced.

## Serving the decisions board

The board is plain static files. Serve the `common/decisions-board/` folder with
**any** static file server and open `decisions.html` (opening via `file://` may
block the `fetch()` of `decisions.json`; serve it instead). For a phone-reachable
board, run a durable static server (launchd/systemd) on your tailnet.

See [`common/docs/ORCHESTRATOR_SESSION.md`](common/docs/ORCHESTRATOR_SESSION.md)
for the in-project doc.
