#!/usr/bin/env bash
# Preview or create an app-schema snapshot, or inspect published readiness
# evidence in S3-compatible storage.
# The default is a true no-op plan. Execution requires a fresh one-use owner
# authorization bound to the exact printed scope digest.

set +x
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=cloud-db-lib.sh
. "$ROOT/scripts/cloud-db-lib.sh"

usage() {
  cat <<'USAGE'
Usage:
  scripts/cloud-snapshot.sh create [--prepare | --execute] [options]
  scripts/cloud-snapshot.sh list

Create options:
  default                   Local-only no-op preview; no credentials required
  --prepare                 Read target identity and print the exact scope
  --environment ID          Non-secret environment alias (default: prod)
  --plan-nonce HEX          Opaque 16-64 lowercase hex characters
  --approval-expires-at N   Unix time, no more than 15 minutes away
  --max-bytes N             Hard archive-size cap (default: 1073741824)
  --execute                 Arm external execution; never sufficient alone
  --authorization-id ID     Fresh owner-supplied one-use identifier
  --approved-scope SHA256   Exact scope_sha256 from the reviewed preview

No URL, credential, account identifier, or production data is printed or
stored in the local intent journal.
USAGE
}

command_name="${1:-create}"
case "$command_name" in
  create|list) shift || true ;;
  -h|--help|help) usage; exit 0 ;;
  *) die "unknown command: $command_name" ;;
esac

if [ "$command_name" = "list" ]; then
  [ "$#" -eq 0 ] || die "list takes no arguments"
  nonsecret_config_ready || exit 0
  require_archive_access
  say "Published snapshot readiness evidence in archive alias $CLOUD_DB_ARCHIVE_ID"
  note "Each exact restore revalidates the marker, manifest, archive bytes, size, checksum, and format."
  rclone_docker lsf "$(archive_dir)" --files-only --max-depth 1 --include '*.ready' --format p \
    | LC_ALL=C sort -r \
    | sed -E 's/[.]ready$/.dump/'
  exit 0
fi

environment=prod
mode=local-plan
plan_nonce="${CLOUD_DB_PLAN_NONCE:-}"
approval_expires_at="${CLOUD_DB_APPROVAL_EXPIRES_AT:-}"
max_bytes="${CLOUD_DB_MAX_SNAPSHOT_BYTES:-1073741824}"
authorization_id="${CLOUD_DB_AUTHORIZATION_ID:-}"
approved_scope="${CLOUD_DB_APPROVED_SCOPE:-}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --environment) shift; environment="${1:-}" ;;
    --plan-nonce) shift; plan_nonce="${1:-}" ;;
    --approval-expires-at) shift; approval_expires_at="${1:-}" ;;
    --max-bytes) shift; max_bytes="${1:-}" ;;
    --prepare) mode=prepare ;;
    --execute) mode=execute ;;
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
if [ "$mode" = local-plan ]; then
  say "Cloud database snapshot local preview (no-op)"
  printf 'format=firestarter-cloud-db-local-plan-v1\n'
  printf 'operation=snapshot-create\n'
  printf 'environment=%s\n' "$environment"
  printf 'source_revision=%s\n' "$revision"
  printf 'migration_set_sha256=%s\n' "$migration_digest"
  note "Nothing was read, written, uploaded, or executed."
  note "Use --prepare with owner-injected credentials to bind the exact database target."
  exit 0
fi

nonsecret_config_ready || die "--prepare/--execute requires cloud recovery configuration"
require_database_access
require_archive_access
load_authorization_key
if [ "$mode" = execute ]; then
  require_source_binding "$revision" "$migration_digest"
fi
target_database_identity="$(database_target_identity)"
target_database_sha256="$(sha256_text "$target_database_identity")"
require_sha256 "$target_database_sha256" "target database identity"

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

object_name="$(snapshot_name "$environment" "$revision" "$approval_expires_at" "$plan_nonce")"
plan="format=firestarter-cloud-db-plan-v1
operation=snapshot-create
environment=$environment
target_id=$CLOUD_DB_TARGET_ID
target_database_sha256=$target_database_sha256
archive_id=$CLOUD_DB_ARCHIVE_ID
archive_config_sha256=$(archive_config_digest)
connection_mode=$CLOUD_DB_CONNECTION_MODE
database_tls_sha256=$(database_tls_digest)
schema=$CLOUD_DB_SCHEMA
snapshot=$object_name
source_revision=$revision
migration_set_sha256=$migration_digest
pg_client_image=$PG_CLIENT_IMAGE
rclone_image=$RCLONE_IMAGE
openssl_image=$OPENSSL_IMAGE
authorization_key_sha256=$authorization_key_sha256
max_snapshot_bytes=$max_bytes
plan_nonce=$plan_nonce
approval_expires_at=$approval_expires_at"
scope="$(sha256_text "$plan")"

say "Cloud database snapshot exact preview"
print_plan "$plan" "$scope"

if [ "$mode" = prepare ]; then
  note "Read-only target discovery only; no snapshot, archive, journal, or other write occurred."
  note "An owner may authorize this exact scope once, before its expiry."
  exit 0
fi

[ "$revision" != unknown ] || die "execution requires a committed source revision"
[ -n "$authorization_id" ] || die "--authorization-id is required for execution"
[ -n "$approved_scope" ] || die "--approved-scope is required for execution"
verify_fresh_authorization snapshot-create "$scope" "$authorization_id" "$approved_scope" "$approval_expires_at" "$object_name"

work_dir="$(new_private_work_dir)"
outcome_recorded=0
cleanup() {
  exit_status=$?
  trap - EXIT
  rm -rf "$work_dir"
  if [ "$exit_status" -ne 0 ] && [ "$outcome_recorded" -eq 0 ] && [ -n "${ACTIVE_AUTHORIZATION_DIR:-}" ]; then
    record_outcome indeterminate snapshot-aborted || true
  fi
  exit "$exit_status"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

create_snapshot "$object_name" "$environment" manual "$max_bytes" "$work_dir" "$revision" "$migration_digest" "$target_database_sha256" "$target_database_identity"
record_outcome verified snapshot-ready
outcome_recorded=1
say "Snapshot verified and published: $CREATED_SNAPSHOT_NAME"
