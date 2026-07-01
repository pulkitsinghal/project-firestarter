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

## What's a follow-up (not in this add-on yet)

The store's identity/session seam is designed for these; wiring them is the next
step, not a rewrite:

1. **Durable sessions.** The default store is in-memory (resets on restart). A
   Postgres-backed `AuthStore` + a migration (`users` / `auth_identities` /
   `auth_sessions` / `auth_otp` / `device_links`) is the durability upgrade —
   swap it in inside `app/main.py`'s lifespan.
2. **OAuth (Google/GitHub).** The store already supports `find_user_by_identity`
   / `link_identity`; add the provider redirect + token-exchange flow (config-
   gated, off until you set client id/secret) and the `/auth/oauth/*` routes.
3. **Frontend sign-in widget.** A small account/OTP widget for the Next.js
   frontend calling the endpoints above.
