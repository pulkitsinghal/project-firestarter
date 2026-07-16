# Remote access to a local/dev service (Tailscale)

A recipe for reaching a stamped project's local dev server or a self-hosted service
**from anywhere** (your phone on cellular, another network) **privately** — without a
public tunnel, a custom domain, a registrar/DNS change, or any paid plan.

Lifted from `local-ai`, where it replaced a rotating Cloudflare quick-tunnel for a
voice-auth phone app. See that repo's `docs/REMOTE_ACCESS.md` for the live example.

## When to reach for this

You want a **stable** remote URL and the usual paths are blocked or heavy: registrar/DNS
changes gated, no budget, and you don't want to expose the service on the public internet.
Tailscale builds a private WireGuard mesh between *your own* devices and hands each a stable
`*.ts.net` MagicDNS name. Nothing is publicly reachable, so it's strictly more private than a
`trycloudflare`/ngrok public tunnel.

Decision order for exposing a service:
1. **Same LAN only** → local Caddy `tls internal` at `<host>.local`.
2. **Your devices, anywhere, private** → **Tailscale `serve`** (this doc). Default for sensitive.
3. **Public internet (strangers)** → Cloudflare Tunnel / Tailscale `funnel`. Never for private data.

## Two ways to run the node — pick by device

### A. Desktop (macOS/Windows/Linux GUI) → the official Tailscale **app**  ← default

On a real desktop, install the official app and sign in. It runs a system extension that wires
**MagicDNS into the OS resolver** (the machine resolves `*.ts.net` natively), is **boot-persistent**,
and gives a tray/menu-bar UI. On macOS the app's CLI is at
`/Applications/Tailscale.app/Contents/MacOS/Tailscale` — use it for `serve`/`status`.

> **macOS caveat that bites:** the Homebrew `tailscaled` **system daemon does NOT configure
> macOS DNS** (no `100.100.100.100` scoped resolver in `scutil --dns`, even with
> `--accept-dns=true`), so the Mac can't resolve its own `*.ts.net` name. Use the **.app** on a
> Mac desktop, not the brew daemon.

```bash
APP=/Applications/Tailscale.app/Contents/MacOS/Tailscale
"$APP" serve --bg --https=443 http://127.0.0.1:<port>   # -> https://<node>.<tailnet>.ts.net/
```

### B. Headless / no-sudo / server / container → rootless **userspace** daemon

For a box with no GUI, no root, or no passwordless sudo (CI runner, VPS, container), run
userspace networking — fully rootless; `serve`/`funnel` still work (they proxy at the app layer):

```bash
mkdir -p ~/.tailscale-userspace
tailscaled --tun=userspace-networking \
  --socket=$HOME/.tailscale-userspace/sock \
  --statedir=$HOME/.tailscale-userspace/state &
S=$HOME/.tailscale-userspace/sock
tailscale --socket=$S up --hostname=<project>          # login URL — the owner taps it
tailscale --socket=$S serve --bg --https=443 http://127.0.0.1:<port>
```

Every later `tailscale` call needs `--socket=$S`. **Caveats:** does not survive reboot; on a
desktop OS it won't provide system DNS (peers still resolve it fine). A stopgap / headless tool,
not the desktop answer.

## Gotchas (both paths)

- **HTTPS certs must be enabled on the tailnet** or `serve --https` fails
  `500 ... account does not support getting TLS certs`. Enable once at the Tailscale admin DNS
  page → **HTTPS Certificates → Enable** (owner action).
- **Secure-context APIs need HTTPS.** `getUserMedia`, `SpeechRecognition`, service workers,
  clipboard, etc. are blocked by the browser over plain HTTP → those services **must** use
  `serve --https`. Plain-HTTP `serve` is only for apps that don't touch a secure-context API.
- **Stale-node / `-1` name.** Switching daemons or re-registering leaves the old node reserving
  the hostname → the new one becomes `<name>-1`. Delete the stale node in the admin console to
  reclaim the clean name, then `serve reset` + re-apply so the TLS cert matches the current name.

Use `serve` (tailnet-only), not `funnel` (public), for private services. The owner's phone joins
the tailnet via the Tailscale app (same account); the `*.ts.net` URL then works from any network.

## Fallback: Cloudflare quick-tunnel (PUBLIC, no client install)

When a viewer **can't be on your tailnet** (lending access to someone who won't install Tailscale,
or a throwaway demo link), `cloudflared tunnel --url http://localhost:<port>` needs no account and
prints a random `https://<words>.trycloudflare.com` URL with real TLS. It's **public**, so only for
non-sensitive / short-lived access. Weaknesses: the URL **rotates on every restart** and the tunnel
**silently deregisters** on network change/idle (process stays up but the host stops resolving —
detect with `dig @1.1.1.1 <host>`, not a local lookup). Make it usable with a **keep-alive watcher**
(a launchd/systemd loop that restarts `cloudflared` when the host stops resolving and re-publishes
the new URL, e.g. via a push notification). For a *durable* public URL, prefer a **named** Cloudflare
tunnel (stable hostname + auto-reconnect), which needs a zone on Cloudflare.
