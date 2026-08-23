# cross_host_agent add-on

Let an agent session on one machine do work that only exists on another, through one
scoped channel rather than an improvised one.

Stack-agnostic, Python-stdlib-only, no daemon, no service.

```
cross_host_agent/
├── README.md                       this file (not stamped into projects)
└── common/                         overlaid when include_cross_host_agent=yes
    ├── bin/agent-host              resolve a capability, run, copy, check, revoke
    ├── bootstrap/{windows.ps1,macos.sh,linux.sh}
    ├── hosts.json                  which host does what, and when the grant ends
    └── docs/CROSS_HOST_AGENT.md
```

## The problem

Some work only exists on one machine: software that is Windows-only, a GPU in one box, a
licensed tool, a build that must happen on the target OS. Without a plan, each occurrence
becomes half an hour of enabling services and guessing at firewall rules, and what gets
left behind is an open port nobody wrote down.

## The properties worth having

**Tailnet-only.** The firewall rule is scoped to the tailnet interface. This is the part
that is easy to get wrong: on Windows a rule created without an explicit profile does not
apply to that adapter, so the port stays shut while every command reports success. The
bootstrap pins it and then verifies by connecting to itself.

**Key-only, never a password.** Password auth is disabled on the channel and the client
passes `BatchMode=yes` and `PasswordAuthentication=no`, so an agent cannot send one even
if something prompts.

**Capabilities, not addresses.** `agent-host run joinpoint -- ...`. Intent stays in a
reviewable manifest instead of shell history, and two hosts offering the same capability
is an error rather than a coin flip.

**Grants expire.** `grant_expires` is mandatory and the client refuses past it. The
default outcome of forgetting a channel is that it closes.

**Revocable and auditable.** `agent-host revoke <host>` gives the exact commands for that
OS. Every invocation appends to a local log.

## Relationship to the other add-ons

| add-on | answers |
|---|---|
| `work_registry` | is a peer already working here? |
| `orchestrator_session` | who owns this task? |
| `convergent_deploy` | what if two of us publish at once? |
| **`cross_host_agent`** | what if the work is on a machine I am not on? |

## Enable

```bash
python3 bin/generate.py --set include_cross_host_agent=yes ...
```

Contract tests: `tests/test_cross_host_agent_contract.py`.
