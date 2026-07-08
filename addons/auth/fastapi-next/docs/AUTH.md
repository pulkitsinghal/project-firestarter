# Authentication (optional add-on)

Passwordless **OTP sign-in** for {{ project_name }}, scaffolded by the `auth`
add-on. Auth is an *upgrade* over an anonymous identity — the base app works
without signing in; signing in links the calling device to an account so state
follows the user across devices.

Enabled at generation time with `include_auth=yes`. Ships with **no external
infrastructure and no new dependencies** (stdlib + FastAPI + pydantic).

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/otp/request` | Issue a 6-digit code for an email/phone (always replies `sent`, no account enumeration). |
| POST | `/auth/otp/verify` | Verify the code → get-or-create the account, link `X-Device-Id`, return a session token. |
| GET | `/auth/me` | The signed-in account (send the token as `Authorization: Bearer …` or `X-Session-Token`). |
| POST | `/auth/logout` | Invalidate the session. |

## Code delivery

Pluggable; nothing paid required.

| Mode | Enable | Result |
|---|---|---|
| On-screen (default, dev) | `AUTH_EXPOSE_DEBUG_OTP=true` | The code is returned in `/auth/otp/request`'s `debug_code` — no mail/SMS needed. **Fail-closed:** leave unset in any shared deployment so the code is never echoed. |
| Real email | set `SMTP_HOST` (+ `SMTP_USERNAME`/`SMTP_PASSWORD`/`SMTP_SENDER`) | Code emailed via stdlib `smtplib` over your own mailbox (Gmail app-password, Fastmail, …). No subscription. |
| Real SMS | — | Not bundled: no SMS transport is free. Phone codes fall back to on-screen/logged. Wiring Twilio/etc. is your call. |

## Configuration (env)

| Var | Default | Meaning |
|---|---|---|
| `AUTH_SECRET` | *(ephemeral per-process)* | HMAC key for codes. **Set this in any shared deployment** — unset means codes/sessions don't survive a restart. Never bake it into an image. |
| `AUTH_OTP_TTL_MIN` | `10` | How long a code is valid. |
| `AUTH_OTP_WINDOW_MIN` | `15` | Rolling window for the rate-limit / brute-force budgets. |
| `AUTH_OTP_MAX_REQUESTS` | `5` | Code requests per identifier per window. |
| `AUTH_OTP_MAX_ATTEMPTS` | `5` | Wrong guesses per identifier per window. |
| `AUTH_SESSION_TTL_DAYS` | `30` | Session lifetime. |

## Security posture (baked in)

- Codes are `secrets`-random 6 digits, stored only as a keyed HMAC-SHA256,
  compared in constant time — a store leak never reveals codes.
- Brute force is bounded by a short expiry + a per-identifier attempt cap that
  survives re-requesting a code.
- Session tokens are 256-bit url-safe randoms; only their SHA-256 is stored.
- Requesting a code never reveals whether an account exists.

## Durable sessions (Postgres)

By default the store is **in-memory** (resets on restart, fine for dev/demo). For
sessions that survive restarts and span workers:

1. Apply the auth schema: it ships as `backend/migrations/002_auth.sql`
   (`users` / `auth_identities` / `auth_otp` / `auth_sessions` / `device_links` /
   `auth_rate_hits`) and is applied by `make migrate` like any other migration.
2. Set **`AUTH_STORE=postgres`** on the backend service. `main.py` then wires
   `PostgresAuthStore` (psycopg3 async, no extra dependency) against `DATABASE_URL`.

`PostgresAuthStore` mirrors the in-memory store's semantics exactly; an
integration test (`tests/test_auth_postgres.py`) drives the full OTP flow through
it and is skipped automatically when no migrated Postgres is reachable.

## Frontend sign-in widget

The add-on ships a Next.js widget (`frontend/app/auth-widget.tsx`) rendered in a
header by the overlaid `layout.tsx`: enter an email → receive a code → verify →
signed in (with a sign-out button). It calls the `/auth/*` endpoints through the
same-origin proxy — the overlaid `next.config.mjs` adds the `/auth/:path*`
rewrite alongside `/api/*`. The session token lives in `localStorage` and is sent
as `X-Session-Token`. In dev (`AUTH_EXPOSE_DEBUG_OTP=true`) the widget shows the
returned code so you can sign in without real email.

## What's a follow-up (not in this add-on yet)

The store's identity/session seam is designed for this; wiring it is the next
step, not a rewrite:

1. **OAuth (Google/GitHub).** The store already supports `find_user_by_identity`
   / `link_identity`; add the provider redirect + token-exchange flow (config-
   gated, off until you set client id/secret) and the `/auth/oauth/*` routes.
