# Beta deploy — one button, no cloud account

Expose a **locally running** {{ project_name }} service on a public URL — no
cloud account, no paid plan, no DNS. Everything stays in Docker.

```bash
make up        # boot postgres + redis + postgrest + gotrue
make migrate   # apply migrations
make pgrst-reload
make deploy    # ← prints a public https://<words>.trycloudflare.com URL
```

`make deploy` runs a [Cloudflare quick tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/).
It needs no token and gives you free TLS. Stop it with `Ctrl-C` or
`make deploy-down`.

## What gets exposed
By default the tunnel points at the **PostgREST API** (`postgrest:3000`) so a
remote client (e.g. a Flutter web build you host elsewhere) can reach the
backend. To expose a served web app instead, edit the `--url` in the
`cloudflared` service in `docker-compose.yml` to point at your web service.

## Deploying edge functions (Supabase Cloud)

Separate from the local tunnel above, `.github/workflows/functions-deploy.yml`
pushes your [Edge Functions](https://supabase.com/docs/guides/functions) to a
Supabase **Cloud** project. Each dir under `backend/supabase/functions/` is one
function (a starter `hello/` ships as an example).

One-time setup (owner):

```bash
gh variable set SUPABASE_PROJECT_REF --body "<your-project-ref>"   # URL subdomain; not secret
gh secret   set SUPABASE_ACCESS_TOKEN                              # sbp_… from dashboard → Account → Access Tokens
```

It then deploys on every push that touches `backend/supabase/functions/**`, or on
demand (Actions → *Deploy edge functions* → *Run workflow*). Until
`SUPABASE_PROJECT_REF` is set the job **skips**, so a fresh stamp stays green.

## Notes
- The quick-tunnel URL is **ephemeral** — changes each run, for short-lived beta
  sharing only.
- For a stable hostname, use a named Cloudflare tunnel with a token.
- Intentionally free-tier friendly; cloud/k8s deploys are per-project, not in the
  template.
