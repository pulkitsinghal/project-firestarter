#!/usr/bin/env bash
#
# RLS guard (Supabase advisor `rls_disabled_in_public`).
#
# The table-level sibling of check_anon_execute.sh. PostgREST + Supabase Cloud
# grant anon/authenticated blanket access to public tables by default, so a
# public table is world-readable/-writable until Row-Level Security is enabled.
# This guard is the continuous backstop: it fails if any APP-DEFINED public table
# has RLS DISABLED but is NOT on the reviewed allow-list
# (backend/security/rls_disabled_allowlist.txt) — catching new exposure the
# moment a migration adds a table without enabling RLS.
#
# Run from the repo root (where docker-compose.yml lives), AFTER all migrations
# are applied (see .github/workflows/rls-guard.yml, which mirrors ci.yml):
#
#   bash backend/security/check_rls_enabled.sh
#
# Env overrides: POSTGRES_SERVICE (postgres), DB_USER (postgres),
#                DB_NAME ({{ db_name }}), ALLOWLIST (defaults next to this script).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
DB_USER="${DB_USER:-postgres}"
DB_NAME="${DB_NAME:-{{ db_name }}}"
ALLOWLIST="${ALLOWLIST:-$SCRIPT_DIR/rls_disabled_allowlist.txt}"

if [ ! -f "$ALLOWLIST" ]; then
  echo "❌ allow-list not found: $ALLOWLIST" >&2
  exit 2
fi

PSQL="docker compose exec -T ${POSTGRES_SERVICE} psql -U ${DB_USER} -d ${DB_NAME} -tA"

# App-defined (non-extension) public tables with RLS DISABLED, by name.
# Extensions (e.g. PostGIS installs spatial_ref_sys into public) are excluded via
# pg_depend deptype 'e' so we only police OUR surface.
read_unprotected() {
  $PSQL -c "
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
      AND c.relrowsecurity = FALSE
      AND NOT EXISTS (
        SELECT 1 FROM pg_depend d
        JOIN pg_extension e ON e.oid = d.refobjid
        WHERE d.objid = c.oid AND d.deptype = 'e')
    ORDER BY 1;
  "
}

unprotected="$(read_unprotected | sed '/^$/d' | sort -u)"
# `|| true`: grep -v exits 1 when the allow-list is all comments/blank (a valid
# state — e.g. a fresh stamp), which would otherwise abort under `set -o pipefail`.
allow="$(grep -vE '^[[:space:]]*(#|$)' "$ALLOWLIST" | tr -d '[:blank:]' | sed '/^$/d' | sort -u || true)"

# unprotected − allow = RLS-off tables nobody signed off on (FAILS).
drift="$(comm -23 <(printf '%s\n' "$unprotected") <(printf '%s\n' "$allow") || true)"
# allow − unprotected = stale allow-list entry (table dropped, or RLS since
# enabled). Advisory only; does not fail the build.
stale="$(comm -13 <(printf '%s\n' "$unprotected") <(printf '%s\n' "$allow") || true)"

n_off="$(printf '%s\n' "$unprotected" | grep -c . || true)"

if [ -n "${stale//[[:space:]]/}" ]; then
  echo "⚠️  allow-listed but RLS is actually ENABLED (or table dropped) — stale entry:"
  printf '   %s\n' $stale
  echo ""
fi

if [ -n "${drift//[[:space:]]/}" ]; then
  echo "❌ RLS drift — these public tables have Row-Level Security DISABLED but are not on the allow-list:"
  printf '   %s\n' $drift
  echo ""
  echo "Fix ONE of:"
  echo "  • protect it (preferred): add 'ALTER TABLE public.<table> ENABLE ROW LEVEL SECURITY;'"
  echo "    in the migration that introduced it. Add a permissive SELECT policy only if the"
  echo "    anon/authenticated client genuinely reads the table directly;"
  echo "  • allow it: add the table name to backend/security/rls_disabled_allowlist.txt"
  echo "    with justification, if RLS-off is deliberate and externally managed."
  exit 1
fi

echo "✅ RLS surface matches the allow-list (${n_off} public app table(s) intentionally RLS-off, all reviewed)."
