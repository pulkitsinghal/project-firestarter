# Reaching another machine from an agent session

An agent session runs on one machine. Some work only exists on another: software that is
Windows-only, a GPU that lives in one box, a licensed tool, a build that must happen on
the target OS. Without a plan for that, every occurrence turns into an improvised half
hour of enabling services and guessing at firewall rules, and what gets left behind is an
open port nobody wrote down.

This add-on makes the channel deliberate: narrow, private to your tailnet, key-only,
declared, and revocable in one command.

## What it is not

Not a remote-execution service, not a daemon, and not a way to hand an agent general
control of your machines. It is a bootstrap that opens **one** scoped channel, a manifest
that records which host can do what, and a thin client that resolves a capability to a
host and runs a command there.

## The security posture, and why each piece is there

**Tailnet-only, never the public internet.** The listener binds to the tailnet address,
not `0.0.0.0`, and the firewall rule is scoped to the tailnet interface. A port opened to
every network to solve a one-off problem is the thing this exists to prevent.

**Key-only authentication.** Password auth is disabled on the channel. An agent must
never be in a position to type a password, and a machine that accepts one invites it.

**A named principal.** Access is granted to a specific key with a comment identifying
which host and which purpose, so `revoke` is a real operation rather than an archaeology
exercise.

**Declared, not discovered.** `hosts.json` states what each host is for. An agent asks
for a capability, not an address. That keeps intent in the repo and out of shell history,
and it means removing a host removes it everywhere.

**Revocable in one command, and expiring by default.** `agent-host revoke <host>` drops
the key, disables the rule, and stops the service. Grants carry an expiry and the client
refuses to use an expired one, so the default outcome of forgetting is closed, not open.

**Auditable.** Every invocation appends to a local log: when, which host, what command,
exit status. Not a security boundary, but the record you want when asking what a session
did on another machine.

## Shape

```
cross_host_agent/
├── bin/agent-host              resolve a capability, run a command, revoke a grant
├── bootstrap/windows.ps1       open the channel on Windows (OpenSSH, tailnet-scoped)
├── bootstrap/macos.sh          open the channel on macOS (Remote Login, tailnet-scoped)
├── bootstrap/linux.sh          open the channel on Linux
├── hosts.json                  which host has which capability, and when the grant ends
└── docs/CROSS_HOST_AGENT.md    this file
```

## Using it

Declare the host and what it is for:

```json
{
  "hosts": [
    {
      "name": "windows-stats",
      "address": "cyberpowerpc",
      "os": "windows",
      "user": "pulki",
      "capabilities": ["joinpoint", "windows-only-software"],
      "grant_expires": "2026-09-22",
      "note": "NCI Joinpoint is Windows only; this box runs it"
    }
  ]
}
```

Open the channel once, on the target machine, in an elevated shell:

```powershell
.\bootstrap\windows.ps1 -TailnetOnly -PublicKey "<the agent host's public key>"
```

Then from anywhere on the tailnet:

```bash
agent-host run joinpoint -- "jpCommand.exe C:\work\series.ini"
agent-host copy ./series.csv joinpoint:C:/work/
agent-host revoke windows-stats
```

`run` resolves the capability to a host, refuses if the grant has expired, executes, logs,
and returns the exit status.

## The bootstrap is the part that has to be got right

Two failures account for most of the lost time, and the scripts handle both explicitly
rather than leaving them to be rediscovered.

**Firewall profile.** On Windows the tailnet adapter is usually classified Public, so a
rule created without an explicit profile silently fails to apply to it. The bootstrap
pins the rule to the tailnet interface and reports which profile it landed on.

**Service enabled but not started, or started but not persistent.** Installing the
capability, starting the service, and setting it to start at boot are three separate
operations and any of them can be the one that was skipped. The bootstrap does all three
and then verifies by connecting to itself, rather than reporting success because no
command threw.
