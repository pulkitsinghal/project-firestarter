#!/usr/bin/env bash
#
# Anon EXECUTE guard.
#
# Postgres grants EXECUTE to PUBLIC by default, and the stack's deny-by-default
# (001_init.sql: `ALTER DEFAULT PRIVILEGES ... REVOKE EXECUTE ... FROM PUBLIC`)
# only covers FUTURE functions created by the migration role. This guard is the
# continuous backstop: it fails if any APP-DEFINED public function is
# anon-EXECUTE-able but NOT on the reviewed allow-list
# (backend/security/anon_execute_allowlist.txt) — catching new exposure the
# moment a migration adds a function without an explicit REVOKE (or with an
# over-broad GRANT).
#
# Run from the repo root (where docker-compose.yml lives), AFTER all migrations
# are applied (see .github/workflows/anon-execute-guard.yml, which mirrors ci.yml):
#
#   bash backend/security/check_anon_execute.sh
#
# Env overrides: POSTGRES_SERVICE (postgres), DB_USER (postgres),
#                DB_NAME ({{ db_name }}), ALLOWLIST (defaults next to this script).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
DB_USER="${DB_USER:-postgres}"
DB_NAME="${DB_NAME:-{{ db_name }}}"
ALLOWLIST="${ALLOWLIST:-$SCRIPT_DIR/anon_execute_allowlist.txt}"

if [ ! -f "$ALLOWLIST" ]; then
  echo "❌ allow-list not found: $ALLOWLIST" >&2
  exit 2
fi

PSQL="docker compose exec -T ${POSTGRES_SERVICE} psql -U ${DB_USER} -d ${DB_NAME} -tA"

# App-defined (non-extension) public functions anon can EXECUTE, by name.
# Extensions (e.g. PostGIS installs hundreds of functions into public) are
# excluded via pg_depend deptype 'e' so we only police OUR surface.
read_exposed() {
  $PSQL -c "
    SELECT DISTINCT p.proname
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND has_function_privilege('anon', p.oid, 'EXECUTE')
      AND NOT EXISTS (
        SELECT 1 FROM pg_depend d
        JOIN pg_extension e ON e.oid = d.refobjid
        WHERE d.objid = p.oid AND d.deptype = 'e')
    ORDER BY 1;
  "
}

exposed="$(read_exposed | sed '/^$/d' | sort -u)"
# `|| true`: grep -v exits 1 when the allow-list is all comments/blank (the fresh-
# stamp default here — no anon-callable RPCs yet), which would otherwise abort
# under `set -o pipefail` and red the guard with no output.
allow="$(grep -vE '^[[:space:]]*(#|$)' "$ALLOWLIST" | tr -d '[:blank:]' | sed '/^$/d' | sort -u || true)"

# exposed − allow  = functions anon can run that nobody signed off on (FAILS).
drift="$(comm -23 <(printf '%s\n' "$exposed") <(printf '%s\n' "$allow") || true)"
# allow − exposed  = stale allow-list entries (e.g. a client-called fn that is
# actually REVOKED — a latent break). Advisory only; does not fail the build.
stale="$(comm -13 <(printf '%s\n' "$exposed") <(printf '%s\n' "$allow") || true)"

n_exposed="$(printf '%s\n' "$exposed" | grep -c . || true)"

if [ -n "${stale//[[:space:]]/}" ]; then
  echo "⚠️  allow-listed but NOT anon-executable (stale entry, or a client call that would fail):"
  printf '   %s\n' $stale
  echo ""
fi

if [ -n "${drift//[[:space:]]/}" ]; then
  echo "❌ anon-EXECUTE drift — these public functions are anon-callable but not on the allow-list:"
  printf '   %s\n' $drift
  echo ""
  echo "Fix ONE of:"
  echo "  • lock it: add 'REVOKE EXECUTE ON FUNCTION public.<fn>(...) FROM PUBLIC, anon, authenticated;'"
  echo "    in the migration that introduced it (preferred for anything not client-facing);"
  echo "  • allow it: add the function name to backend/security/anon_execute_allowlist.txt"
  echo "    (INTENDED section) with justification, if the client genuinely calls it."
  exit 1
fi

echo "✅ anon EXECUTE surface matches the allow-list (${n_exposed} app functions exposed, all reviewed)."
