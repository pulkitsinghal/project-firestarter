#!/bin/bash
#
# Idempotent, forward-only migration runner for {{ project_name }}.
#
# - Iterates ./migrations/*.sql in lexical order
# - Tracks applied versions in a {{ migrations_table }} table
# - Skips versions that have already been applied
# - Aborts on the first SQL error (ON_ERROR_STOP=1)
#
# Environment overrides:
#   MIGRATIONS_DIR    (default: ./migrations)
#   POSTGRES_SERVICE  (default: postgres)
#   DB_USER           (default: postgres)
#   DB_NAME           (default: {{ db_name }})
#
set -euo pipefail

MIGRATIONS_DIR="${MIGRATIONS_DIR:-./migrations}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
DB_USER="${DB_USER:-postgres}"
DB_NAME="${DB_NAME:-{{ db_name }}}"

PSQL="docker compose exec -T ${POSTGRES_SERVICE} psql -U ${DB_USER} -d ${DB_NAME}"

# Bootstrap migration history table.
# RLS is enabled deny-all: this is internal migration bookkeeping that no
# anon/authenticated client ever reads, and PostgREST/Supabase Cloud would
# otherwise expose it (public table, RLS off). The runner connects as an
# owner/superuser and bypasses RLS, so tracking still works — this just keeps the
# table off the public RLS surface so `backend/security/check_rls_enabled.sh` is
# green on a fresh project without allow-listing it. ENABLE is idempotent.
${PSQL} -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
CREATE TABLE IF NOT EXISTS {{ migrations_table }} (
    version    TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE {{ migrations_table }} ENABLE ROW LEVEL SECURITY;
SQL

shopt -s nullglob
files=("${MIGRATIONS_DIR}"/*.sql)
shopt -u nullglob

if [ ${#files[@]} -eq 0 ]; then
    echo "No migrations found in ${MIGRATIONS_DIR}"
    exit 0
fi

# Sort filenames lexically; matches ls -1 | sort behavior across shells.
IFS=$'\n' sorted=($(printf '%s\n' "${files[@]}" | sort))
unset IFS

applied_count=0
for file in "${sorted[@]}"; do
    # `version` is the migration file BASENAME (e.g. `001_init`), stored as TEXT.
    # GOTCHA: keep this format consistent with every CONSUMER of the column. A
    # "latest applied migration" check that casts or orders numerically
    # (`MAX(version::int)`, `ORDER BY version::int`) throws on a non-numeric
    # basename. Record a numeric-castable version here, or don't cast downstream —
    # never mismatch the two: a non-numeric basename recorded here will make a
    # downstream `MAX(version::int)` / `ORDER BY version::int` throw on the first row.
    version="$(basename "${file}" .sql)"
    is_applied="$(${PSQL} -tA -c "SELECT 1 FROM {{ migrations_table }} WHERE version = '${version}';" | tr -d '[:space:]')"
    if [ "${is_applied}" = "1" ]; then
        echo "✓ ${version} (already applied)"
        continue
    fi
    echo "→ Applying ${version}..."
    ${PSQL} -v ON_ERROR_STOP=1 < "${file}"
    ${PSQL} -v ON_ERROR_STOP=1 -c "INSERT INTO {{ migrations_table }} (version) VALUES ('${version}');" >/dev/null
    echo "✓ ${version} (applied)"
    applied_count=$((applied_count + 1))
done

echo ""
echo "Migrations complete: ${applied_count} applied, $((${#sorted[@]} - applied_count)) already current."
