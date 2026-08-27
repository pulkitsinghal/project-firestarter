#!/usr/bin/env bash
# Restore one exact verified snapshot into an attested, empty isolated drill
# target. This intentionally refuses production and same-environment targets.
# A project-specific owner runbook remains the only production restore path.

set +x
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=cloud-db-lib.sh
. "$ROOT/scripts/cloud-db-lib.sh"

usage() {
  cat <<'USAGE'
Usage: scripts/cloud-restore.sh SNAPSHOT [--prepare | --execute] [options]

  default                       Local-only no-op explanation
  --prepare                     Validate archive + empty isolated target; print scope
  --execute                     Arm the reviewed drill; never sufficient alone
  --environment ID              Destination alias (default: restore-drill)
  --target-attestation ID       Owner-reviewed isolated-target evidence reference
  --verification-plan ID        Project-specific verification-plan reference
  --plan-nonce HEX              Opaque 16-64 lowercase hex characters
  --approval-expires-at N       Unix time, no more than 15 minutes away
  --max-bytes N                 Hard download/archive cap
  --max-sql-bytes N             Hard rendered-restore cap (default: 4294967296)
  --authorization-id ID         Fresh owner-supplied one-use identifier
  --approved-scope SHA256       Exact scope_sha256 from --prepare

`latest`, production targets, non-empty app schemas, weak TLS, and transaction
pooler connections are refused. This command never creates extensions.
USAGE
}

requested_snapshot="${1:-}"
case "$requested_snapshot" in
  -h|--help|help|"") usage; exit 0 ;;
esac
shift
[ "$requested_snapshot" != latest ] || die "restore requires one exact immutable snapshot name; latest is not an authorization target"
require_snapshot_name "$requested_snapshot"

mode=local-plan
environment=restore-drill
target_attestation="${CLOUD_DB_TARGET_ATTESTATION:-}"
verification_plan="${CLOUD_DB_VERIFICATION_PLAN:-}"
plan_nonce="${CLOUD_DB_PLAN_NONCE:-}"
approval_expires_at="${CLOUD_DB_APPROVAL_EXPIRES_AT:-}"
max_bytes="${CLOUD_DB_MAX_SNAPSHOT_BYTES:-1073741824}"
max_sql_bytes="${CLOUD_DB_MAX_RESTORE_SQL_BYTES:-4294967296}"
authorization_id="${CLOUD_DB_AUTHORIZATION_ID:-}"
approved_scope="${CLOUD_DB_APPROVED_SCOPE:-}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --prepare) mode=prepare ;;
    --execute) mode=execute ;;
    --environment) shift; environment="${1:-}" ;;
    --target-attestation) shift; target_attestation="${1:-}" ;;
    --verification-plan) shift; verification_plan="${1:-}" ;;
    --plan-nonce) shift; plan_nonce="${1:-}" ;;
    --approval-expires-at) shift; approval_expires_at="${1:-}" ;;
    --max-bytes) shift; max_bytes="${1:-}" ;;
    --max-sql-bytes) shift; max_sql_bytes="${1:-}" ;;
    --authorization-id) shift; authorization_id="${1:-}" ;;
    --approved-scope) shift; approved_scope="${1:-}" ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done

require_safe_id "$environment" "environment"
require_byte_cap "$max_bytes" "maximum snapshot bytes"
require_byte_cap "$max_sql_bytes" "maximum rendered restore bytes"
if [ "$mode" = local-plan ]; then
  say "Isolated restore-drill local preview (no-op)"
  printf 'format=firestarter-cloud-db-local-plan-v1\n'
  printf 'operation=isolated-restore-drill\n'
  printf 'snapshot=%s\n' "$requested_snapshot"
  note "Nothing was read, written, downloaded, or executed."
  note "Use --prepare only after provisioning an empty target expressly for a restore drill."
  note "Production restoration remains a separate project-specific owner runbook."
  exit 0
fi

nonsecret_config_ready || die "--prepare/--execute requires cloud recovery configuration"
[ "${CLOUD_DB_TARGET_KIND:-}" = isolated-drill ] \
  || die "CLOUD_DB_TARGET_KIND must be isolated-drill; production restore is intentionally unsupported"
require_database_access
require_archive_access
load_authorization_key
[ -n "$target_attestation" ] || die "--target-attestation is required"
[ -n "$verification_plan" ] || die "--verification-plan is required"
require_safe_id "$target_attestation" "target attestation"
require_safe_id "$verification_plan" "verification plan"

work_dir="$(new_private_work_dir)"
outcome_recorded=0
cleanup() {
  exit_status=$?
  trap - EXIT
  rm -rf "$work_dir"
  if [ "$exit_status" -ne 0 ] && [ "$outcome_recorded" -eq 0 ] && [ -n "${ACTIVE_AUTHORIZATION_DIR:-}" ]; then
    record_outcome indeterminate restore-drill-aborted || true
  fi
  exit "$exit_status"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

fetch_snapshot_evidence "$requested_snapshot" "$work_dir"
source_target_id="$(manifest_value source_target_id "$FETCHED_MANIFEST_FILE")"
require_safe_id "$source_target_id" "snapshot source target"
[ "$source_target_id" != "$CLOUD_DB_TARGET_ID" ] \
  || die "restore drill target equals the snapshot source; same-target/production restore is refused"
source_database_sha256="$(manifest_value source_database_sha256 "$FETCHED_MANIFEST_FILE")"
require_sha256 "$source_database_sha256" "snapshot source database identity"
destination_database_identity="$(database_target_identity)"
destination_database_sha256="$(sha256_text "$destination_database_identity")"
require_sha256 "$destination_database_sha256" "destination database identity"
[ "$source_database_sha256" != "$destination_database_sha256" ] \
  || die "restore drill database equals the snapshot source; same-target/production restore is refused"

target_app_objects="$(pg_docker psql -X -tA -v ON_ERROR_STOP=1 -c \
  "select count(*) from (select 'pg_class'::regclass as classid, c.oid from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='$CLOUD_DB_SCHEMA' union all select 'pg_proc'::regclass, p.oid from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='$CLOUD_DB_SCHEMA' union all select 'pg_type'::regclass, t.oid from pg_type t join pg_namespace n on n.oid=t.typnamespace where n.nspname='$CLOUD_DB_SCHEMA') app_object where not exists (select 1 from pg_depend d where d.classid=app_object.classid and d.objid=app_object.oid and d.deptype in ('e','i'))" \
  | tr -d '[:space:]')"
require_uint "$target_app_objects" "isolated target app-object count"
[ "$target_app_objects" -eq 0 ] || die "isolated target already has app-owned objects; refusing destructive or ambiguous restore"

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

manifest_sha256="$(sha256_file "$FETCHED_MANIFEST_FILE")"
plan="format=firestarter-cloud-db-plan-v1
operation=isolated-restore-drill
environment=$environment
source_target_id=$source_target_id
source_database_sha256=$source_database_sha256
destination_target_id=$CLOUD_DB_TARGET_ID
destination_database_sha256=$destination_database_sha256
destination_kind=isolated-drill
target_attestation=$target_attestation
verification_plan=$verification_plan
archive_id=$CLOUD_DB_ARCHIVE_ID
archive_config_sha256=$(archive_config_digest)
connection_mode=$CLOUD_DB_CONNECTION_MODE
database_tls_sha256=$(database_tls_digest)
schema=$CLOUD_DB_SCHEMA
snapshot=$requested_snapshot
snapshot_sha256=$FETCHED_SNAPSHOT_SHA256
snapshot_bytes=$FETCHED_SNAPSHOT_BYTES
manifest_sha256=$manifest_sha256
target_app_objects=0
pg_client_image=$PG_CLIENT_IMAGE
rclone_image=$RCLONE_IMAGE
openssl_image=$OPENSSL_IMAGE
authorization_key_sha256=$authorization_key_sha256
max_snapshot_bytes=$max_bytes
max_restore_sql_bytes=$max_sql_bytes
plan_nonce=$plan_nonce
approval_expires_at=$approval_expires_at"
scope="$(sha256_text "$plan")"

say "Isolated restore-drill exact preview"
print_plan "$plan" "$scope"
if [ "$mode" = prepare ]; then
  note "Only archive and target reads occurred; no database, archive, journal, or local durable write occurred."
  note "An owner may authorize this exact isolated-drill scope once, before its expiry."
  exit 0
fi

[ -n "$authorization_id" ] || die "--authorization-id is required for execution"
[ -n "$approved_scope" ] || die "--approved-scope is required for execution"
require_clean_source
download_and_verify_snapshot "$requested_snapshot" "$work_dir" "$max_bytes"
verify_fresh_authorization isolated-restore-drill "$scope" "$authorization_id" "$approved_scope" "$approval_expires_at" "$requested_snapshot"

restore_list="$work_dir/restore.list"
docker_run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges -v "$VERIFIED_SNAPSHOT_FILE:/snapshot.dump:ro" "$PG_CLIENT_IMAGE" \
  pg_restore --list /snapshot.dump \
  | awk '/ SCHEMA - public / { print ";" $0; next } { print }' > "$restore_list"
[ -s "$restore_list" ] || die "archive table-of-contents inspection failed"
if grep -Eq ' EXTENSION( | - )' "$restore_list"; then
  die "archive attempts to create an extension; precreate extensions in the isolated target"
fi

restore_sql="$work_dir/restore.sql"
set +e
docker_run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  -v "$VERIFIED_SNAPSHOT_FILE:/snapshot.dump:ro" \
  -v "$restore_list:/restore.list:ro" \
  "$PG_CLIENT_IMAGE" pg_restore --use-list=/restore.list --schema=public \
    --strict-names --no-owner --no-privileges --file=- /snapshot.dump \
  | head -c "$((max_sql_bytes + 1))" > "$restore_sql"
render_status=("${PIPESTATUS[@]}")
set -e
rendered_bytes="$(wc -c < "$restore_sql" | tr -d '[:space:]')"
require_uint "$rendered_bytes" "rendered restore bytes"
[ "$rendered_bytes" -le "$max_sql_bytes" ] \
  || die "rendered restore exceeded its byte cap before any database write"
[ "${render_status[0]}" -eq 0 ] && [ "${render_status[1]}" -eq 0 ] \
  || die "pg_restore failed before producing a complete restore program; no database write occurred"
[ -s "$restore_sql" ] || die "pg_restore produced an empty restore program"

restore_apply_sql="$work_dir/restore-apply.sql"
cat > "$restore_apply_sql" <<'SQL'
\set ON_ERROR_STOP on
select (control.system_identifier || ':' || database.oid) = :'expected_database_identity' as firestarter_identity_matches
from pg_control_system() control
cross join pg_database database
where database.datname = current_database()
\gset
\if :firestarter_identity_matches
\else
\echo isolated restore target identity changed on the writer connection
\quit 3
\endif
select pg_advisory_xact_lock(hashtextextended('firestarter-cloud-restore-v1', 0));
do $guard$
begin
  if exists (
    select 1
    from (
      select 'pg_class'::regclass as classid, c.oid
      from pg_class c join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public'
      union all
      select 'pg_proc'::regclass, p.oid
      from pg_proc p join pg_namespace n on n.oid = p.pronamespace
      where n.nspname = 'public'
      union all
      select 'pg_type'::regclass, t.oid
      from pg_type t join pg_namespace n on n.oid = t.typnamespace
      where n.nspname = 'public'
    ) app_object
    where not exists (
      select 1 from pg_depend d
      where d.classid = app_object.classid
        and d.objid = app_object.oid
        and d.deptype in ('e', 'i')
    )
  ) then
    raise exception 'isolated target app scope is no longer empty';
  end if;
end
$guard$;
\i /restore.sql
SQL

say "Restoring into the empty isolated drill target in one transaction"
pg_docker_run --rm \
    -e PGHOST -e PGPORT -e PGDATABASE -e PGUSER -e PGPASSWORD -e PGSSLMODE -e PGSSLROOTCERT \
    --cap-drop ALL --security-opt no-new-privileges \
    -v "$restore_sql:/restore.sql:ro" \
    -v "$restore_apply_sql:/restore-apply.sql:ro" \
    --entrypoint psql "$PG_CLIENT_IMAGE" \
      -X -v ON_ERROR_STOP=1 -v "expected_database_identity=$destination_database_identity" \
      --single-transaction -f /restore-apply.sql \
  || die "isolated restore failed atomically; authorization is consumed"

record_outcome pending application-verification-required
outcome_recorded=1
say "Isolated restore completed atomically for snapshot $requested_snapshot"
note "Status is pending, not verified. Run the referenced application/data/security verification plan."
note "This command grants no production-restore authority."
