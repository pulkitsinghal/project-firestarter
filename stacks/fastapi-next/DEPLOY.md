# Beta deploy — one button, no cloud account

Expose your **locally running** {{ project_name }} on a public URL so others can
try it — no cloud account, no paid plan, no DNS. Everything stays in Docker.

```bash
make up        # boot the stack (postgres, redis, backend, frontend)
make migrate   # apply migrations
make deploy    # ← prints a public https://<words>.trycloudflare.com URL
```

`make deploy` runs a [Cloudflare quick tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/)
in front of the `frontend` service. It needs no token and gives you free TLS.
Share the printed URL; stop it with `Ctrl-C` or `make deploy-down`.

The quick-tunnel URL is **ephemeral** — it changes each run and is meant for
short-lived beta sharing, not production.

## Stable named tunnel (your own domain)

For a **stable** hostname on a domain you control, use a *named* tunnel. Still
free, still all in Docker — it just needs a Cloudflare account with your domain
added. One-time setup (run `cloudflared` on the host, or via
`docker run --rm -it -v "$PWD/deploy/cloudflared:/etc/cloudflared" cloudflare/cloudflared`):

```bash
cloudflared tunnel login                          # authorize your account + domain
cloudflared tunnel create {{ project_slug }}      # writes a <UUID>.json credentials file
cp deploy/cloudflared/config.example.yml deploy/cloudflared/config.yml
# edit config.yml: set `tunnel`/`credentials-file` to the <UUID>, `hostname` to yours
cloudflared tunnel route dns {{ project_slug }} <YOUR_HOSTNAME>   # one-time DNS route
```

Then run it — `make tunnel` mounts `deploy/cloudflared/` into a `cloudflared`
container and serves your hostname off `config.yml`, stable across restarts:

```bash
make up          # the frontend must be running (published on :{{ port_web }})
make tunnel      # serves https://<YOUR_HOSTNAME> → the frontend
```

`config.yml` and the `<UUID>.json` credentials are **gitignored** (tunnel
secrets) — never commit them. `deploy/cloudflared/config.example.yml` is the
tracked template.

## Notes
- This is intentionally free-tier friendly. Heavier targets (a real cloud
  deploy, k8s) are out of scope for the template — add them per project.
