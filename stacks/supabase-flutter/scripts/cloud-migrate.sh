#!/usr/bin/env bash
# Incremental cloud migration driver. The default only inspects local migration
# files. --prepare performs read-only target discovery. --execute first creates
# and verifies an immutable recovery point; there is no backup bypass.

set +x
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=cloud-db-lib.sh
. "$ROOT/scripts/cloud-db-lib.sh"

usage() {
  cat <<'USAGE'
Usage: scripts/cloud-migrate.sh [--prepare | --execute] [options]

  default                    Local-only no-op preview; no credentials required
  --prepare                  Read live migration history and print exact scope
  --execute                  Arm the reviewed scope; never sufficient alone
  --environment ID           Non-secret environment alias (default: prod)
  --plan-nonce HEX           Opaque 16-64 lowercase hex characters
  --approval-expires-at N    Unix time, no more than 15 minutes away
  --max-bytes N              Hard pre-migration snapshot cap
  --authorization-id ID      Fresh owner-supplied one-use identifier
  --approved-scope SHA256    Exact scope_sha256 from --prepare

Production migration fails closed unless its pre-migration snapshot is fully
uploaded, checksum-verified, and marked ready. There is no skip flag.
USAGE
}

mode=local-plan
environment=prod
plan_nonce="${CLOUD_DB_PLAN_NONCE:-}"
approval_expires_at="${CLOUD_DB_APPROVAL_EXPIRES_AT:-}"
max_bytes="${CLOUD_DB_MAX_SNAPSHOT_BYTES:-1073741824}"
authorization_id="${CLOUD_DB_AUTHORIZATION_ID:-}"
approved_scope="${CLOUD_DB_APPROVED_SCOPE:-}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --prepare) mode=prepare ;;
    --execute) mode=execute ;;
    --environment) shift; environment="${1:-}" ;;
    --plan-nonce) shift; plan_nonce="${1:-}" ;;
    --approval-expires-at) shift; approval_expires_at="${1:-}" ;;
    --max-bytes) shift; max_bytes="${1:-}" ;;
    --authorization-id) shift; authorization_id="${1:-}" ;;
    --approved-scope) shift; approved_scope="${1:-}" ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done

require_safe_id "$environment" "environment"
require_byte_cap "$max_bytes" "maximum snapshot bytes"
revision="$(source_revision)"
migration_digest="$(migration_set_digest)"
local_migrations="$(find "$ROOT/backend/migrations" -maxdepth 1 -type f -name '*.sql' -print \
  | LC_ALL=C sort)"
local_count=0
while IFS= read -r migration_path; do
  [ -n "$migration_path" ] || continue
  migration_name="$(basename "$migration_path" .sql)"
  printf '%s' "$migration_name" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$' \
    || die "migration filename is unsafe for the cloud runner: $migration_name"
  local_count=$((local_count + 1))
done <<EOF
$local_migrations
EOF

if [ "$mode" = local-plan ]; then
  say "Cloud migration local preview (no-op)"
  printf 'format=firestarter-cloud-db-local-plan-v1\n'
  printf 'operation=cloud-migrate\n'
  printf 'source_revision=%s\n' "$revision"
  printf 'migration_set_sha256=%s\n' "$migration_digest"
  printf 'local_migration_count=%s\n' "$local_count"
  note "Nothing was read from or written to a database, archive, Docker daemon, or local state."
  note "Use --prepare with owner-injected read credentials to resolve the exact pending set."
  exit 0
fi

nonsecret_config_ready || die "--prepare/--execute requires cloud recovery configuration"
require_database_access
require_archive_access
load_authorization_key

collect_migration_state() {
  target_database_identity="$(database_target_identity)"
  target_database_sha256="$(sha256_text "$target_database_identity")"
  require_sha256 "$target_database_sha256" "target database identity"
  table_exists="$(pg_docker psql -X -tA -v ON_ERROR_STOP=1 \
    -c "select to_regclass('public.$CLOUD_DB_MIGRATIONS_TABLE') is not null" | tr -d '[:space:]')"
  if [ "$table_exists" = t ]; then
    applied_versions="$(pg_docker psql -X -tA -v ON_ERROR_STOP=1 \
      -c "select version from public.$CLOUD_DB_MIGRATIONS_TABLE order by version")"
  else
    applied_versions=""
  fi
  while IFS= read -r applied_version; do
    [ -n "$applied_version" ] || continue
    printf '%s' "$applied_version" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$' \
      || die "target migration history contains an unsafe version value"
  done <<EOF
$applied_versions
EOF
  applied_versions_sha256="$(sha256_text "$applied_versions")"
  pending_versions=""
  while IFS= read -r migration_path; do
    [ -n "$migration_path" ] || continue
    migration_name="$(basename "$migration_path" .sql)"
    if ! printf '%s\n' "$applied_versions" | grep -Fxq "$migration_name"; then
      if [ -n "$pending_versions" ]; then
        pending_versions="$pending_versions
$migration_name"
      else
        pending_versions="$migration_name"
      fi
    fi
  done <<EOF
$local_migrations
EOF
  pending_versions_sha256="$(sha256_text "$pending_versions")"
  pending_count="$(printf '%s\n' "$pending_versions" | awk 'NF { count++ } END { print count + 0 }')"
}

collect_migration_state
if [ "$pending_count" -eq 0 ]; then
  say "Cloud migration preview"
  note "No pending migration exists. No snapshot, authorization, or database write is needed."
  exit 0
fi

if [ -z "$plan_nonce" ]; then
  [ "$mode" = prepare ] || die "--plan-nonce is required for execution"
  plan_nonce="$(new_nonce)"
fi
printf '%s' "$plan_nonce" | grep -Eq '^[0-9a-f]{16,64}$' || die "plan nonce must be 16-64 lowercase hex characters"
if [ -z "$approval_expires_at" ]; then
  [ "$mode" = prepare ] || die "--approval-expires-at is required for execution"
  approval_expires_at=$(( $(now_epoch) + CLOUD_DB_APPROVAL_MAX_TTL_SECONDS ))
fi
require_uint "$approval_expires_at" "approval expiry"

snapshot_object="$(snapshot_name "$environment" "$revision" "$approval_expires_at" "$plan_nonce" '-pre-migrate')"
plan="format=firestarter-cloud-db-plan-v1
operation=cloud-migrate
environment=$environment
target_id=$CLOUD_DB_TARGET_ID
target_database_sha256=$target_database_sha256
archive_id=$CLOUD_DB_ARCHIVE_ID
archive_config_sha256=$(archive_config_digest)
connection_mode=$CLOUD_DB_CONNECTION_MODE
database_tls_sha256=$(database_tls_digest)
schema=$CLOUD_DB_SCHEMA
source_revision=$revision
migration_set_sha256=$migration_digest
applied_migrations_sha256=$applied_versions_sha256
pending_migrations_sha256=$pending_versions_sha256
pending_migration_count=$pending_count
pre_migration_snapshot=$snapshot_object
pg_client_image=$PG_CLIENT_IMAGE
rclone_image=$RCLONE_IMAGE
openssl_image=$OPENSSL_IMAGE
sql_guard_image=$PYTHON_SQL_GUARD_IMAGE
authorization_key_sha256=$authorization_key_sha256
max_snapshot_bytes=$max_bytes
plan_nonce=$plan_nonce
approval_expires_at=$approval_expires_at"
scope="$(sha256_text "$plan")"

say "Cloud migration exact preview"
print_plan "$plan" "$scope"
printf 'pending_migrations:\n%s\n' "$pending_versions"
if [ "$mode" = prepare ]; then
  note "Read-only discovery only; no snapshot, migration, journal, or other write occurred."
  note "An owner may authorize this exact scope once, before its expiry."
  exit 0
fi

[ "$revision" != unknown ] || die "execution requires a committed source revision"
[ -n "$authorization_id" ] || die "--authorization-id is required for execution"
[ -n "$approved_scope" ] || die "--approved-scope is required for execution"
require_source_binding "$revision" "$migration_digest"

work_dir="$(new_private_work_dir)"
outcome_recorded=0
cleanup() {
  exit_status=$?
  trap - EXIT
  chmod -R u+w "$work_dir" 2>/dev/null || true
  rm -rf "$work_dir"
  if [ "$exit_status" -ne 0 ] && [ "$outcome_recorded" -eq 0 ] && [ -n "${ACTIVE_AUTHORIZATION_DIR:-}" ]; then
    record_outcome indeterminate migration-aborted || true
  fi
  exit "$exit_status"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

staged_migrations="$work_dir/migrations"
mkdir -p "$staged_migrations"
while IFS= read -r migration_path; do
  [ -n "$migration_path" ] || continue
  cp -- "$migration_path" "$staged_migrations/$(basename "$migration_path")"
done <<EOF
$local_migrations
EOF
staged_migration_digest="$({
  while IFS= read -r migration_path; do
    [ -n "$migration_path" ] || continue
    migration_name="$(basename "$migration_path")"
    printf 'backend/migrations/%s\n' "$migration_name"
    sha256_file "$staged_migrations/$migration_name"
  done <<EOF
$local_migrations
EOF
} | sha256_stream)"
[ "$staged_migration_digest" = "$migration_digest" ] \
  || die "migration bytes changed while staging the approved set"
chmod -R a-w "$staged_migrations" 2>/dev/null || true

say "Rejecting migration input that can escape the runner transaction"
docker_run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  -v "$ROOT/scripts/check-cloud-migration-sql.py:/guard/check.py:ro" \
  -v "$staged_migrations:/migrations:ro" \
  --entrypoint python "$PYTHON_SQL_GUARD_IMAGE" /guard/check.py /migrations \
  || die "cloud migration SQL preflight rejected the approved file set"

verify_fresh_authorization cloud-migrate "$scope" "$authorization_id" "$approved_scope" "$approval_expires_at" "$snapshot_object"

create_snapshot "$snapshot_object" "$environment" pre-migrate "$max_bytes" "$work_dir" "$revision" "$migration_digest" "$target_database_sha256" "$target_database_identity"

planned_applied="$applied_versions"
planned_pending="$pending_versions"
planned_target_database_sha256="$target_database_sha256"
planned_target_database_identity="$target_database_identity"
collect_migration_state
if [ "$target_database_sha256" != "$planned_target_database_sha256" ] \
  || [ "$target_database_identity" != "$planned_target_database_identity" ] \
  || [ "$applied_versions" != "$planned_applied" ] \
  || [ "$pending_versions" != "$planned_pending" ]; then
  record_outcome blocked target-state-drift
  outcome_recorded=1
  die "target migration state changed after approval; snapshot is safe, but migration is blocked"
fi

expected_applied_file="$work_dir/expected-applied.txt"
printf '%s\n' "$planned_applied" | awk 'NF' > "$expected_applied_file"
apply_sql="$work_dir/apply.sql"
require_source_binding "$revision" "$migration_digest"
{
  printf '\\set ON_ERROR_STOP on\n'
  printf "select (control.system_identifier || ':' || database.oid) = :'expected_database_identity' as firestarter_identity_matches from pg_control_system() control cross join pg_database database where database.datname=current_database() \\gset\n"
  printf '\\if :firestarter_identity_matches\n'
  printf '\\else\n'
  printf '\\echo cloud migration target identity changed on the writer connection\n'
  printf '\\quit 3\n'
  printf '\\endif\n'
  printf "select pg_advisory_xact_lock(hashtextextended('firestarter-cloud-migrate-v1', 0));\n"
  printf 'create table if not exists public.%s (version text primary key, applied_at timestamptz not null default current_timestamp);\n' "$CLOUD_DB_MIGRATIONS_TABLE"
  printf 'alter table public.%s enable row level security;\n' "$CLOUD_DB_MIGRATIONS_TABLE"
  printf 'lock table public.%s in exclusive mode;\n' "$CLOUD_DB_MIGRATIONS_TABLE"
  printf 'create temporary table firestarter_expected_migrations (version text primary key) on commit drop;\n'
  printf "\\copy firestarter_expected_migrations(version) from '/expected-applied.txt' with (format text)\n"
  printf 'do $guard$ begin if exists ((select version from public.%s except select version from firestarter_expected_migrations) union all (select version from firestarter_expected_migrations except select version from public.%s)) then raise exception '\''migration scope drift after lock'\''; end if; end $guard$;\n' "$CLOUD_DB_MIGRATIONS_TABLE" "$CLOUD_DB_MIGRATIONS_TABLE"
  while IFS= read -r migration_name; do
    [ -n "$migration_name" ] || continue
    printf '\\i /migrations/%s.sql\n' "$migration_name"
    printf "insert into public.%s(version) values ('%s');\n" "$CLOUD_DB_MIGRATIONS_TABLE" "$migration_name"
  done <<EOF
$planned_pending
EOF
} > "$apply_sql"

say "Applying the approved migration set in one transaction"
pg_docker_run --rm \
    -e PGHOST -e PGPORT -e PGDATABASE -e PGUSER -e PGPASSWORD -e PGSSLMODE -e PGSSLROOTCERT \
    --cap-drop ALL --security-opt no-new-privileges \
    -v "$staged_migrations:/migrations:ro" \
    -v "$expected_applied_file:/expected-applied.txt:ro" \
    -v "$apply_sql:/apply.sql:ro" \
    --entrypoint psql "$PG_CLIENT_IMAGE" \
      -X -v ON_ERROR_STOP=1 -v "expected_database_identity=$planned_target_database_identity" \
      --single-transaction -f /apply.sql \
  || die "cloud migration failed atomically; recovery point is ready and authorization is consumed"

collect_migration_state
if [ "$pending_count" -ne 0 ]; then
  die "migration call returned but the target history is incomplete; outcome is indeterminate"
fi

record_outcome verified migrations-applied
outcome_recorded=1
say "Cloud migrations applied after verified snapshot $CREATED_SNAPSHOT_NAME"
