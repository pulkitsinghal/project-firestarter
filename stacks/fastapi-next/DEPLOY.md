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

## Notes
- The quick-tunnel URL is **ephemeral** — it changes each run and is meant for
  short-lived beta sharing, not production.
- For a stable hostname, set up a named Cloudflare tunnel with a token and swap
  the `cloudflared` command in `docker-compose.yml`.
- This is intentionally free-tier friendly. Heavier targets (a real cloud
  deploy, k8s) are out of scope for the template — add them per project.
