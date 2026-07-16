# Remote access to a local/dev service (Tailscale)

A recipe for reaching a stamped project's local dev server or a self-hosted service
**from anywhere** (your phone on cellular, another network) **privately** — without a
public tunnel, a custom domain, a registrar/DNS change, root on the box, or any paid plan.

Lifted from `local-ai`, where it replaced a rotating Cloudflare quick-tunnel for a
voice-auth phone app. See that repo's `docs/REMOTE_ACCESS.md` for the live example.

## When to reach for this

You want a **stable** remote URL and the usual paths are blocked or heavy:
no passwordless `sudo`, registrar/DNS changes gated or unavailable, you don't want to pay,
and you don't want to expose the service on the public internet. Tailscale builds a private
WireGuard mesh between *your own* devices and hands each a stable `*.ts.net` MagicDNS name.
Nothing is publicly reachable, so it's strictly more private than a `trycloudflare`/ngrok
public tunnel.

Decision order for exposing a service:
1. **Same LAN only** → local Caddy `tls internal` at `<host>.local` (see the generated
   project's TLS docs).
2. **Your devices, anywhere, private** → **Tailscale `serve`** (this doc). Default for
   anything sensitive.
3. **Public internet (non-your devices)** → Cloudflare Tunnel / Tailscale `funnel`. Only when
   strangers must reach it; never for private data.

## Rootless setup (no sudo)

`tailscaled` wants root for a TUN device. With no passwordless sudo, run **userspace
networking** — fully rootless; `serve`/`funnel` still work (they proxy at the app layer):

```bash
mkdir -p ~/.tailscale-userspace
tailscaled --tun=userspace-networking \
  --socket=$HOME/.tailscale-userspace/sock \
  --statedir=$HOME/.tailscale-userspace/state &
S=$HOME/.tailscale-userspace/sock
tailscale --socket=$S up --hostname=<project>   # prints a login URL — the owner taps it
```

Every later `tailscale` call needs `--socket=$S`. **Caveat:** this instance does not survive
reboot. For boot-persistence use `sudo tailscaled install-system-daemon` or the Tailscale
desktop app — both need the owner at the machine with sudo.

## Expose the service

```bash
# HTTP is fine for apps that don't need a browser "secure context":
tailscale --socket=$S serve --bg --http=80   http://127.0.0.1:<port>
# HTTPS (valid cert, no warning) for apps that do:
tailscale --socket=$S serve --bg --https=443 http://127.0.0.1:<port>
#   -> https://<project>.<tailnet>.ts.net/
```

Use `serve` (tailnet-only), not `funnel` (public), for private services.

### Two gotchas that will bite you

- **HTTPS certs must be enabled on the tailnet** or `serve --https` fails with
  `500 ... account does not support getting TLS certs`. Enable once at the Tailscale admin
  DNS page → **HTTPS Certificates → Enable** (owner action).
- **Secure-context APIs need HTTPS.** Anything using `getUserMedia`, `SpeechRecognition`,
  service workers, clipboard, etc. is blocked by the browser over plain HTTP. Those services
  **must** use `serve --https` (⇒ enable HTTPS certs first). Plain-HTTP `serve` is only for
  apps that don't touch a secure-context API.

The owner's phone joins the tailnet via the Tailscale app (same account); the `*.ts.net`
URL then works from any network.
