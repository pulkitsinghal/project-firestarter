#!/usr/bin/env bash
# Rotate this stack's secrets away from the dev-only insecure defaults.
#
# Generates a fresh JWT_SECRET + DB_PASSWORD, mints matching anon + service_role
# JWTs, and writes them to .env.deploy (gitignored, chmod 600). Nothing here
# touches a running stack — apply the new secrets by pointing compose at the file:
#
#   docker compose --env-file .env.deploy up -d --build
#
# Why this matters: docker-compose.yml defaults GOTRUE_JWT_SECRET to a well-known
# dev-only value (`${JWT_SECRET:-dev-only-insecure-change-me-...}`). Anyone who
# knows that default can mint a valid token, so ROTATE BEFORE the stack is
# publicly reachable (see SECURITY.md — "no default/guessable secret in deploy
# configs"). PostgREST must be given the SAME JWT_SECRET in PGRST_JWT_SECRET once
# you wire JWT auth, so tokens minted by GoTrue validate.
#
# What each secret is for in this stack:
#   JWT_SECRET      — live now: overrides the compose default above.
#   DB_PASSWORD     — for when you parameterize POSTGRES_PASSWORD (compose ships
#                     `postgres` for local dev); rotate it before exposing the DB.
#   anon / service  — the two PostgREST role JWTs a Flutter/splash frontend (or a
#                     JWT-gated PostgREST) will use — minted here off the fresh
#                     secret so you never ship keys tied to the dev default.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env.deploy"

command -v openssl >/dev/null || { echo "✗ openssl required" >&2; exit 1; }

# Mint an HS256 JWT ({role, iss, far-future exp}) in a throwaway container so no
# Node lives on the host (the "no host SDKs" rule).
mint_jwt() {
  docker run --rm -e ROLE="$1" -e SECRET="$2" node:20-alpine node -e '
    const c=require("crypto");
    const b=o=>Buffer.from(JSON.stringify(o)).toString("base64url");
    const iat=Math.floor(Date.now()/1000), exp=iat+60*60*24*3650;
    const h=b({alg:"HS256",typ:"JWT"});
    const p=b({role:process.env.ROLE,iss:"{{ project_slug }}-selfhost",iat,exp});
    const d=h+"."+p;
    const s=c.createHmac("sha256",process.env.SECRET).update(d).digest("base64url");
    process.stdout.write(d+"."+s);'
}

echo "▶ Generating fresh secrets…"
JWT_SECRET="$(openssl rand -hex 48)"
DB_PASSWORD="$(openssl rand -hex 24)"
ANON="$(mint_jwt anon "$JWT_SECRET")"
SERVICE="$(mint_jwt service_role "$JWT_SECRET")"

# Upsert keys into .env.deploy (portable: BSD/macOS + GNU). Preserve other lines.
touch "$ENV_FILE"
tmp="$(mktemp)"
grep -vE '^(JWT_SECRET|DB_PASSWORD|SUPABASE_ANON_KEY|SUPABASE_SERVICE_KEY)=' "$ENV_FILE" > "$tmp" || true
{
  cat "$tmp"
  echo "JWT_SECRET=$JWT_SECRET"
  echo "DB_PASSWORD=$DB_PASSWORD"
  echo "SUPABASE_ANON_KEY=$ANON"
  echo "SUPABASE_SERVICE_KEY=$SERVICE"
} > "$ENV_FILE"
rm -f "$tmp"
chmod 600 "$ENV_FILE" 2>/dev/null || true

echo "✓ Rotated. Wrote JWT_SECRET, DB_PASSWORD, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY"
echo "  → $ENV_FILE (gitignored, chmod 600)"
echo ""
echo "  Apply to the stack:  docker compose --env-file .env.deploy up -d --build"
echo "  (or: make rotate-secrets, then re-run make up with the env file)"
