# Remote agent access — hardened spec (decision doc, not a default)

Sometimes you want a remote agent (or a teammate off your LAN) to drive
{{ project_name }}'s local Docker stack — run a migration, restart a service,
read logs. This doc is how to do that **safely**. It is a *decision doc*: the
template ships **no executable that opens remote Docker access**, on purpose. Read
this, pick a pattern, and own the trade-off.

> **The one rule:** never expose the raw Docker socket (`/var/run/docker.sock`)
> over a tunnel. The socket is **root-equivalent** — anyone who can reach it can
> start a privileged container that mounts the host filesystem and take over the
> machine. "Just an ngrok tunnel to docker.sock" is a full remote-root backdoor,
> even behind a random URL (URLs leak; there is no auth on the socket).

## Prefer: trigger, don't connect (recommended)

The safest remote control is **no inbound access at all** — the agent triggers
work that runs locally, and never holds a live handle to Docker.

- **`workflow_dispatch` on a self-hosted runner.** This is already shipped:
  [`deploy.yml`](../.github/workflows/deploy.yml). Register a self-hosted runner
  on the machine; the agent (or you, or a schedule) clicks/►API-calls "Run
  workflow"; GitHub authenticates the trigger and the job runs `make …` locally.
  No socket is exposed; GitHub's auth + audit log do the heavy lifting. Add more
  dispatchable workflows (migrate, restart, logs-tail-to-artifact) the same way.
- **A scheduled task / queue the machine polls.** The stack pulls a job list from
  a place the agent can write to; nothing inbound is opened.

If a trigger-based pattern covers your need, **stop here** — you don't need any of
what follows.

## If you truly need interactive control

…then put a **hardened, authenticated broker** in front of Docker — never the
socket itself. Minimum bar, all of them:

1. **Never the raw socket.** Expose a *purpose-built* endpoint that accepts only
   an **allowlist** of commands (e.g. `migrate`, `restart <known-service>`,
   `logs <known-service>`) — not arbitrary `docker`/`compose` args. Reject
   everything else. No shell passthrough.
2. **Mutual authentication.** mTLS (client cert) or a strong bearer token that is
   *not* the tunnel URL. Rotate it; store it out of band; fail closed if unset
   (see [SECURITY.md](../SECURITY.md) — no default/guessable secrets).
3. **Transport encryption + pinning.** TLS end to end; verify the cert. A tunnel
   URL is not a credential and not confidentiality.
4. **Least privilege.** The broker runs as a non-root user in its own container
   with only the specific capabilities it needs — not `--privileged`, not the
   host socket bind.
5. **Time-boxed + revocable.** Access is on for a session, then off. A single
   command kills it. Default state is **off**.
6. **Audit log.** Every accepted command is logged with who/when/what, to a place
   the operator (not the caller) controls.
7. **Bind to loopback behind the tunnel.** The broker listens on `127.0.0.1`; the
   authenticated tunnel is the only path in. Nothing binds `0.0.0.0`.

## Threat model (why the bar is this high)

| Threat | Mitigation |
|---|---|
| Socket = remote root | Never expose it; allowlisted broker only |
| URL/token leak | mTLS/bearer + rotation + time-box; URL ≠ auth |
| Passive MITM on the hop | TLS with cert verification |
| Command injection / arg abuse | Fixed allowlist, no shell/`docker` passthrough |
| Standing backdoor | Off by default; session-scoped; one-command kill |
| "Who did that?" | Per-command audit log the operator owns |

## Checklist before you enable anything

- [ ] The raw Docker socket is **not** reachable from any tunnel or non-loopback bind.
- [ ] Every remote action is on a fixed allowlist; arbitrary commands are rejected.
- [ ] mTLS or a rotated bearer token is required; it's read from the env, fail-closed.
- [ ] Access is time-boxed and killable with one command; default is off.
- [ ] Accepted commands are audit-logged.
- [ ] You considered the trigger-based pattern first and it genuinely didn't fit.
