# Work registry — look before you touch

When several agents or sessions run against one machine, they can silently edit the same
files. This is a one-file noticeboard that lets them see each other.

It is **advisory**. It tells you who is working where; it does not stop anyone.

## Before starting work on a shared directory

```bash
registry.py check ~/development/some-repo        # exit 1 if someone else holds it
registry.py claim ~/development/some-repo --intent "rewriting the build script" --ttl 3600
```

If it is held, the output tells you who, since when, what they said they were doing, and
when their claim expires. Talk to them, or wait, or `--force` and say why.

## While working

```bash
registry.py heartbeat ~/development/some-repo    # extends the claim
```

## When done

```bash
registry.py release ~/development/some-repo
```

## Seeing everything in flight

```bash
registry.py list          # live claims
registry.py list --all    # including expired, useful for "what happened last night"
```

## Set a stable identity

`claim`, `heartbeat` and `release` are separate processes, so identity cannot be the pid.
Export a session identifier once:

```bash
export WORK_REGISTRY_OWNER="ali-video-session"
```

Without it the tool falls back to a terminal-session hash, and warns if it cannot find
even that.

## Where the file lives

`~/.firestarter/work-registry.json`, override with `WORK_REGISTRY`.

## If you need real mutual exclusion

You want `orchestrator_session`, not this. It has proper leases with fencing tokens and
safe takeover. This tool cannot stop a write and does not pretend to.
