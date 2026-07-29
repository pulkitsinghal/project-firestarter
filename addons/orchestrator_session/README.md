# orchestrator_session add-on

Bootstrap a master-orchestrator session governed by one canonical
[`ORCHESTRATOR_BILL_OF_RIGHTS.md`](common/ORCHESTRATOR_BILL_OF_RIGHTS.md).
The add-on is stack-agnostic, dependency-free, and generic.

The Bill consolidates the reusable policy for a PM proxy, scoped
conversation-derived learning, routine delivery, bounded owner gates, visible
nonduplicative queues with blocked-work re-audits, exact-candidate/default
evidence, truthful CI, closure and successor handoff, canonical repo/path
ownership and cleanup, privacy/identity, and never-go-dark reporting.

## What's in here

```
orchestrator_session/
├── README.md                          # this file (addon-level, not stamped into projects)
└── common/                            # overlaid into a project when include_orchestrator_session=yes
    ├── ORCHESTRATOR_BILL_OF_RIGHTS.md # authoritative orchestrator policy
    ├── ORCHESTRATOR_PROMPT.md         # thin paste-in pointer to the Bill
    ├── AGENTS.orchestrator.md         # thin paste-able pointer to the Bill
    ├── docs/ORCHESTRATOR_SESSION.md   # the house-style add-on doc that lands in a stamped project
    └── decisions-board/
        ├── decisions.json             # starter schema + 2–3 EXAMPLE items to replace
        └── decisions.html             # self-contained dark-mode-aware viewer (no deps)
```

## Very easy setup (three steps)

1. Put `ORCHESTRATOR_BILL_OF_RIGHTS.md` and `ORCHESTRATOR_PROMPT.md` together at
   the root of your projects/portfolio (stamping the add-on does this).
2. Open a fresh capable-agent session at that root and paste the contents of
   [`common/ORCHESTRATOR_PROMPT.md`](common/ORCHESTRATOR_PROMPT.md).
3. Go.

That's it — no install, no config. Optionally, paste the "Orchestrator posture"
section from
[`common/AGENTS.orchestrator.md`](common/AGENTS.orchestrator.md) into your
`AGENTS.md` so every future session resolves the same Bill automatically.

To vendor these files into a generated project instead, stamp with the add-on on:

```bash
./bin/firestart.sh --set include_orchestrator_session=yes
```

## Contract

- The Bill is the only authoritative orchestrator policy in the add-on.
- `ORCHESTRATOR_PROMPT.md` and `AGENTS.orchestrator.md` are thin pointers, so
  summaries cannot drift into competing rules.
- A stdlib contract test stamps every declared stack with
  `include_orchestrator_session=yes`, requires every add-on file, and proves the
  stamped Bill is byte-for-byte identical to the canonical source. It also pins
  the failure-prevention clauses so they cannot disappear in a prose refactor.
- The decisions board remains the visible queue/status view; it is not a second
  policy source.

## What it deliberately does NOT include

- **No owner-specific configuration** — no private repos, hostnames, ports,
  schedules, secrets, or personal decision history. The Bill is usable by anyone;
  active scope supplies portfolio policy.
- **No dependencies and no host toolchain** — the policy and pointers are text,
  and the board is a single self-contained HTML file plus JSON. Nothing to
  install or run on the host.
- **No credentials or network calls** baked in. The board's example items are
  clearly labeled placeholders meant to be replaced.

## Serving the decisions board

The board is plain static files. Serve the `common/decisions-board/` folder with
**any** static file server and open `decisions.html` (opening via `file://` may
block the `fetch()` of `decisions.json`; serve it instead). For a phone-reachable
board, run a durable static server (launchd/systemd) on your tailnet.

See [`common/docs/ORCHESTRATOR_SESSION.md`](common/docs/ORCHESTRATOR_SESSION.md)
for the in-project doc.
