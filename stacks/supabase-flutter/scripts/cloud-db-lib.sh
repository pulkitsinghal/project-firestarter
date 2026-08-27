#!/usr/bin/env bash
# Shared, provider-neutral primitives for the Supabase cloud recovery commands.
# This file is sourced by cloud-snapshot.sh, cloud-migrate.sh, and
# cloud-restore.sh; it is not a standalone command.

set +x
set -euo pipefail

PG_CLIENT_IMAGE="postgres:17.10-alpine@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"
RCLONE_IMAGE="rclone/rclone:1.75.0@sha256:b06aed988cf5967de7c25be5925240983981c757f4ed1ac9d2fa659d51d60548"
OPENSSL_IMAGE="alpine/openssl:3.5.4@sha256:42c7389ef077aed0eb4e96d0abbd094083d701bbaff1313073b061c0c9cd8278"
PYTHON_SQL_GUARD_IMAGE="python:3.13-bookworm@sha256:62eafe52c91cad83c2c74e630bfde917da8c253673e695665d454def84fc9a13"
CLOUD_DB_SCHEMA="public"
CLOUD_DB_MIGRATIONS_TABLE="{{ migrations_table }}"
CLOUD_DB_APPROVAL_MAX_TTL_SECONDS=900
PG_CA_DOCKER_ARGS=()
PGSSLROOTCERT_VALUE=system
database_ca_sha256=""

printf '%s' "$CLOUD_DB_MIGRATIONS_TABLE" | grep -Eq '^[a-z][a-z0-9_]{0,62}$' \
  || { printf '\nERROR: generated migrations-table identifier is unsafe\n' >&2; exit 1; }

say() { printf '\n==> %s\n' "$*"; }
note() { printf '    %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
docker_run() {
  MSYS2_ARG_CONV_EXCL='*' MSYS2_ENV_CONV_EXCL='PGSSLROOTCERT' docker run "$@"
}

pg_docker_run() {
  local -x PGHOST="$CLOUD_DB_HOST"
  local -x PGPORT="${CLOUD_DB_PORT:-5432}"
  local -x PGDATABASE="$CLOUD_DB_NAME"
  local -x PGUSER="$CLOUD_DB_USER"
  local -x PGPASSWORD="$CLOUD_DB_PASSWORD"
  local -x PGSSLMODE=verify-full
  local -x PGSSLROOTCERT="$PGSSLROOTCERT_VALUE"
  docker_run "${PG_CA_DOCKER_ARGS[@]}" "$@"
}

sha256_stream() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 | awk '{print $1}'
  else
    die "sha256sum or shasum is required"
  fi
}

sha256_text() { printf '%s' "$1" | sha256_stream; }
sha256_file() { sha256_stream < "$1"; }

require_safe_id() {
  value="$1"
  label="$2"
  printf '%s' "$value" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,95}$' \
    || die "$label must be 1-96 safe, non-secret identifier characters"
}

require_snapshot_name() {
  value="$1"
  printf '%s' "$value" | grep -Eq '^fsdb-[A-Za-z0-9._+-]+-[0-9]{10}-[0-9a-f]{7,40}-[0-9a-f]{16,64}(-(pre-restore|pre-migrate))?\.dump$' \
    || die "invalid snapshot name; path components and unbound object names are refused"
}

require_uint() {
  value="$1"
  label="$2"
  printf '%s' "$value" | grep -Eq '^[0-9]+$' || die "$label must be an unsigned integer"
}

require_byte_cap() {
  value="$1"
  label="$2"
  require_uint "$value" "$label"
  [ "$value" -ge 1 ] && [ "$value" -le 10737418240 ] \
    || die "$label must be between 1 byte and 10 GiB"
}

require_sha256() {
  value="$1"
  label="$2"
  printf '%s' "$value" | grep -Eq '^[0-9a-f]{64}$' || die "$label must be a lowercase SHA-256 digest"
}

require_prefix() {
  value="$1"
  [ -n "$value" ] || die "CLOUD_DB_ARCHIVE_PREFIX must not be empty"
  case "$value" in
    /*|*..*|*//*|*/|*\\*) die "CLOUD_DB_ARCHIVE_PREFIX must be a safe relative object prefix" ;;
  esac
  printf '%s' "$value" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._/-]{0,159}$' \
    || die "CLOUD_DB_ARCHIVE_PREFIX contains unsafe characters"
}

now_epoch() { date -u +%s; }

new_nonce() {
  od -An -N16 -tx1 /dev/urandom | tr -d ' \n'
}

source_revision() {
  git -C "$ROOT" rev-parse HEAD 2>/dev/null || printf 'unknown\n'
}

require_clean_source() {
  git -C "$ROOT" rev-parse --verify HEAD >/dev/null 2>&1 \
    || die "execution requires a committed source revision"
  [ -z "$(git -C "$ROOT" status --porcelain --untracked-files=all 2>/dev/null)" ] \
    || die "execution requires a clean source checkout bound to the printed revision"
}

require_source_binding() {
  expected_revision="$1"
  expected_migration_digest="$2"
  require_clean_source
  [ "$(source_revision)" = "$expected_revision" ] \
    || die "source revision changed after the reviewed plan"
  [ "$(migration_set_digest)" = "$expected_migration_digest" ] \
    || die "migration files changed after the reviewed plan"
}

ensure_recovery_state_dir() {
  state_parent="$ROOT/.firestarter"
  state_dir="$state_parent/cloud-db-recovery"
  [ ! -L "$state_parent" ] || die "recovery state parent must not be a symlink"
  [ ! -L "$state_dir" ] || die "recovery state directory must not be a symlink"
  umask 077
  mkdir -p "$state_dir"
  physical_root="$(cd "$ROOT" && pwd -P)"
  physical_state="$(cd "$state_dir" && pwd -P)"
  [ "$physical_state" = "$physical_root/.firestarter/cloud-db-recovery" ] \
    || die "recovery state path escaped the project root"
  chmod 700 "$state_dir" 2>/dev/null || true
  RECOVERY_STATE_DIR="$state_dir"
}

new_private_work_dir() {
  ensure_recovery_state_dir
  mktemp -d "$RECOVERY_STATE_DIR/work.XXXXXX"
}

migration_set_digest() {
  migration_root="$ROOT/backend/migrations"
  [ -d "$migration_root" ] || { sha256_text 'no-migrations'; return; }
  (
    cd "$ROOT"
    find backend/migrations -type f -name '*.sql' -print \
      | LC_ALL=C sort \
      | while IFS= read -r migration_file; do
          printf '%s\n' "$migration_file"
          sha256_file "$migration_file"
        done
  ) | sha256_stream
}

archive_prefix() { printf '%s\n' "${CLOUD_DB_ARCHIVE_PREFIX:-db-snapshots}"; }

nonsecret_config_ready() {
  missing=""
  [ -n "${CLOUD_DB_TARGET_ID:-}" ] || missing="$missing CLOUD_DB_TARGET_ID"
  [ -n "${CLOUD_DB_ARCHIVE_ID:-}" ] || missing="$missing CLOUD_DB_ARCHIVE_ID"
  [ -n "${CLOUD_DB_ARCHIVE_BUCKET:-}" ] || missing="$missing CLOUD_DB_ARCHIVE_BUCKET"
  [ -n "${CLOUD_DB_CONNECTION_MODE:-}" ] || missing="$missing CLOUD_DB_CONNECTION_MODE"
  if [ -n "$missing" ]; then
    note "SKIP: cloud recovery is not configured; set:$missing"
    note "No database, object-store, or Docker call was made."
    return 1
  fi
  require_safe_id "$CLOUD_DB_TARGET_ID" "CLOUD_DB_TARGET_ID"
  require_safe_id "$CLOUD_DB_ARCHIVE_ID" "CLOUD_DB_ARCHIVE_ID"
  case "$CLOUD_DB_CONNECTION_MODE" in
    direct|session) ;;
    *) die "CLOUD_DB_CONNECTION_MODE must be direct or session; transaction pooling is unsafe for dump/restore" ;;
  esac
  require_prefix "$(archive_prefix)"
  return 0
}

require_database_access() {
  [ -z "${CLOUD_DB_URL:-}" ] \
    || die "CLOUD_DB_URL is not accepted because URI options can override reviewed transport controls; use the discrete CLOUD_DB_* fields"
  [ -n "${CLOUD_DB_HOST:-}" ] || die "CLOUD_DB_HOST is required"
  printf '%s' "$CLOUD_DB_HOST" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$' \
    || die "CLOUD_DB_HOST must be a bounded DNS hostname"
  require_uint "${CLOUD_DB_PORT:-5432}" "CLOUD_DB_PORT"
  [ "${CLOUD_DB_PORT:-5432}" -ge 1 ] && [ "${CLOUD_DB_PORT:-5432}" -le 65535 ] \
    || die "CLOUD_DB_PORT must be between 1 and 65535"
  [ -n "${CLOUD_DB_NAME:-}" ] || die "CLOUD_DB_NAME is required"
  printf '%s' "$CLOUD_DB_NAME" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$' \
    || die "CLOUD_DB_NAME must be a bounded safe database name"
  [ -n "${CLOUD_DB_USER:-}" ] || die "CLOUD_DB_USER is required"
  printf '%s' "$CLOUD_DB_USER" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._@+-]{0,127}$' \
    || die "CLOUD_DB_USER must be a bounded safe role name"
  [ -n "${CLOUD_DB_PASSWORD:-}" ] || die "CLOUD_DB_PASSWORD is required"
  [ "${#CLOUD_DB_PASSWORD}" -le 8192 ] || die "CLOUD_DB_PASSWORD exceeds the 8192-byte safety bound"
  case "$CLOUD_DB_PASSWORD" in
    *$'\n'*|*$'\r'*) die "CLOUD_DB_PASSWORD must not contain a line break" ;;
  esac
  [ "${CLOUD_DB_SSLMODE:-verify-full}" = verify-full ] \
    || die "CLOUD_DB_SSLMODE must be verify-full; unauthenticated TLS is refused"
  PG_CA_DOCKER_ARGS=()
  PGSSLROOTCERT_VALUE=system
  database_ca_sha256="$(sha256_text 'system-trust')"
  if [ -n "${CLOUD_DB_SSLROOTCERT_FILE:-}" ]; then
    db_ca_relative="$CLOUD_DB_SSLROOTCERT_FILE"
    case "$db_ca_relative" in
      /*|*..*|*//*|*\*) die "database CA path must be a safe project-relative path" ;;
    esac
    printf '%s' "$db_ca_relative" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._/-]{0,159}$' \
      || die "database CA path is unsafe"
    database_ca_file="$ROOT/$db_ca_relative"
    [ -f "$database_ca_file" ] && [ ! -L "$database_ca_file" ] \
      || die "database CA must be a regular non-symlink file"
    git -C "$ROOT" ls-files --error-unmatch -- "$db_ca_relative" >/dev/null 2>&1 \
      || die "database CA must be committed in the project"
    physical_root="$(cd "$ROOT" && pwd -P)"
    physical_database_ca="$(cd "$(dirname "$database_ca_file")" && pwd -P)/$(basename "$database_ca_file")"
    [ "$physical_database_ca" = "$physical_root/$db_ca_relative" ] \
      || die "database CA path traverses a linked component"
    database_ca_bytes="$(wc -c < "$database_ca_file" | tr -d '[:space:]')"
    require_uint "$database_ca_bytes" "database CA bytes"
    [ "$database_ca_bytes" -gt 0 ] && [ "$database_ca_bytes" -le 1048576 ] \
      || die "database CA must be 1 byte to 1 MiB"
    grep -Fq -- '-----BEGIN CERTIFICATE-----' "$database_ca_file" \
      || die "database CA file must contain a PEM certificate"
    database_ca_sha256="$(sha256_file "$database_ca_file")"
    PG_CA_DOCKER_ARGS=(-v "$database_ca_file:/firestarter-db-ca/ca.pem:ro")
    PGSSLROOTCERT_VALUE=/firestarter-db-ca/ca.pem
  fi
}

database_tls_digest() {
  sha256_text "sslmode=verify-full
ca-sha256=$database_ca_sha256"
}

require_archive_access() {
  [ -n "${AWS_ACCESS_KEY_ID:-}" ] || die "AWS_ACCESS_KEY_ID is required for the S3-compatible archive"
  [ -n "${AWS_SECRET_ACCESS_KEY:-}" ] || die "AWS_SECRET_ACCESS_KEY is required for the S3-compatible archive"
  provider="${CLOUD_DB_S3_PROVIDER:-Other}"
  require_safe_id "$provider" "CLOUD_DB_S3_PROVIDER"
  require_safe_id "${CLOUD_DB_S3_REGION:-us-east-1}" "CLOUD_DB_S3_REGION"
  printf '%s' "$CLOUD_DB_ARCHIVE_BUCKET" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$' \
    || die "CLOUD_DB_ARCHIVE_BUCKET is unsafe"
  if [ "$provider" != "AWS" ] && [ -z "${CLOUD_DB_S3_ENDPOINT:-}" ]; then
    die "CLOUD_DB_S3_ENDPOINT is required unless CLOUD_DB_S3_PROVIDER=AWS"
  fi
  if [ -n "${CLOUD_DB_S3_ENDPOINT:-}" ]; then
    printf '%s' "$CLOUD_DB_S3_ENDPOINT" \
      | grep -Eq '^https://[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]{1,5})?(/[A-Za-z0-9._~!$&()*+,;=:@%/-]*)?$' \
      || die "CLOUD_DB_S3_ENDPOINT must be an HTTPS endpoint without credentials, query, or fragment"
  fi
  RCLONE_CA_DOCKER_ARGS=()
  RCLONE_CA_CLI_ARGS=()
  if [ -n "${CLOUD_DB_S3_CA_CERT_FILE:-}" ]; then
    ca_relative="$CLOUD_DB_S3_CA_CERT_FILE"
    case "$ca_relative" in
      /*|*..*|*//*|*\*) die "archive CA path must be a safe project-relative path" ;;
    esac
    printf '%s' "$ca_relative" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._/-]{0,159}$' \
      || die "archive CA path is unsafe"
    archive_ca_file="$ROOT/$ca_relative"
    [ -f "$archive_ca_file" ] && [ ! -L "$archive_ca_file" ] \
      || die "archive CA must be a regular non-symlink file"
    git -C "$ROOT" ls-files --error-unmatch -- "$ca_relative" >/dev/null 2>&1 \
      || die "archive CA must be committed in the project"
    physical_root="$(cd "$ROOT" && pwd -P)"
    physical_ca="$(cd "$(dirname "$archive_ca_file")" && pwd -P)/$(basename "$archive_ca_file")"
    [ "$physical_ca" = "$physical_root/$ca_relative" ] \
      || die "archive CA path traverses a linked component"
    ca_bytes="$(wc -c < "$archive_ca_file" | tr -d '[:space:]')"
    require_uint "$ca_bytes" "archive CA bytes"
    [ "$ca_bytes" -gt 0 ] && [ "$ca_bytes" -le 1048576 ] \
      || die "archive CA must be 1 byte to 1 MiB"
    grep -Fq -- '-----BEGIN CERTIFICATE-----' "$archive_ca_file" \
      || die "archive CA file must contain a PEM certificate"
    archive_ca_sha256="$(sha256_file "$archive_ca_file")"
    RCLONE_CA_DOCKER_ARGS=(-v "$archive_ca_file:/firestarter-ca/ca.pem:ro")
    RCLONE_CA_CLI_ARGS=(--ca-cert /firestarter-ca/ca.pem)
  else
    archive_ca_sha256="$(sha256_text 'system-trust')"
  fi
}

load_authorization_key() {
  key_relative="${CLOUD_DB_AUTHORIZATION_PUBLIC_KEY_FILE:-}"
  [ -n "$key_relative" ] || die "CLOUD_DB_AUTHORIZATION_PUBLIC_KEY_FILE is required for live preparation/execution"
  case "$key_relative" in
    /*|*..*|*//*|*\*) die "authorization public-key path must be a safe project-relative path" ;;
  esac
  printf '%s' "$key_relative" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._/-]{0,159}$' \
    || die "authorization public-key path is unsafe"
  authorization_public_key="$ROOT/$key_relative"
  [ -f "$authorization_public_key" ] && [ ! -L "$authorization_public_key" ] \
    || die "authorization public key must be a regular non-symlink file"
  git -C "$ROOT" ls-files --error-unmatch -- "$key_relative" >/dev/null 2>&1 \
    || die "authorization public key must be committed in the project"
  physical_root="$(cd "$ROOT" && pwd -P)"
  physical_key="$(cd "$(dirname "$authorization_public_key")" && pwd -P)/$(basename "$authorization_public_key")"
  [ "$physical_key" = "$physical_root/$key_relative" ] \
    || die "authorization public-key path traverses a linked component"
  key_bytes="$(wc -c < "$authorization_public_key" | tr -d '[:space:]')"
  require_uint "$key_bytes" "authorization public-key bytes"
  [ "$key_bytes" -gt 0 ] && [ "$key_bytes" -le 16384 ] \
    || die "authorization public key must be 1-16384 bytes"
  grep -Fq -- '-----BEGIN PUBLIC KEY-----' "$authorization_public_key" \
    || die "authorization file must contain a PEM public key"
  if grep -Fq -- 'PRIVATE KEY' "$authorization_public_key"; then
    die "authorization file must never contain a private key"
  fi
  authorization_key_sha256="$(sha256_file "$authorization_public_key")"
}

archive_config_digest() {
  prefix="$(archive_prefix)"
  sha256_text "archive-id=${CLOUD_DB_ARCHIVE_ID}
provider=${CLOUD_DB_S3_PROVIDER:-Other}
endpoint=${CLOUD_DB_S3_ENDPOINT:-}
region=${CLOUD_DB_S3_REGION:-us-east-1}
bucket=${CLOUD_DB_ARCHIVE_BUCKET}
prefix=$prefix
ca-sha256=$archive_ca_sha256"
}

archive_dir() {
  printf 'archive:%s/%s\n' "$CLOUD_DB_ARCHIVE_BUCKET" "$(archive_prefix)"
}

archive_object() { printf '%s/%s\n' "$(archive_dir)" "$1"; }

rclone_docker() {
  RCLONE_CONFIG_ARCHIVE_TYPE=s3 \
  RCLONE_CONFIG_ARCHIVE_PROVIDER="${CLOUD_DB_S3_PROVIDER:-Other}" \
  RCLONE_CONFIG_ARCHIVE_ENV_AUTH=true \
  RCLONE_CONFIG_ARCHIVE_ENDPOINT="${CLOUD_DB_S3_ENDPOINT:-}" \
  RCLONE_CONFIG_ARCHIVE_REGION="${CLOUD_DB_S3_REGION:-us-east-1}" \
  RCLONE_CONFIG_ARCHIVE_ACL=private \
  docker_run --rm "${RCLONE_CA_DOCKER_ARGS[@]}" \
    --cap-drop ALL --security-opt no-new-privileges \
    -e RCLONE_CONFIG_ARCHIVE_TYPE \
    -e RCLONE_CONFIG_ARCHIVE_PROVIDER \
    -e RCLONE_CONFIG_ARCHIVE_ENV_AUTH \
    -e RCLONE_CONFIG_ARCHIVE_ENDPOINT \
    -e RCLONE_CONFIG_ARCHIVE_REGION \
    -e RCLONE_CONFIG_ARCHIVE_ACL \
    -e AWS_ACCESS_KEY_ID \
    -e AWS_SECRET_ACCESS_KEY \
    -e AWS_SESSION_TOKEN \
    "$RCLONE_IMAGE" "${RCLONE_CA_CLI_ARGS[@]}" "$@"
}

rclone_upload() {
  local_file="$1"
  remote="$2"
  docker_mount="$local_file:/transfer/item:ro"
  RCLONE_CONFIG_ARCHIVE_TYPE=s3 \
  RCLONE_CONFIG_ARCHIVE_PROVIDER="${CLOUD_DB_S3_PROVIDER:-Other}" \
  RCLONE_CONFIG_ARCHIVE_ENV_AUTH=true \
  RCLONE_CONFIG_ARCHIVE_ENDPOINT="${CLOUD_DB_S3_ENDPOINT:-}" \
  RCLONE_CONFIG_ARCHIVE_REGION="${CLOUD_DB_S3_REGION:-us-east-1}" \
  RCLONE_CONFIG_ARCHIVE_ACL=private \
  docker_run --rm -v "$docker_mount" "${RCLONE_CA_DOCKER_ARGS[@]}" \
    --cap-drop ALL --security-opt no-new-privileges \
    -e RCLONE_CONFIG_ARCHIVE_TYPE \
    -e RCLONE_CONFIG_ARCHIVE_PROVIDER \
    -e RCLONE_CONFIG_ARCHIVE_ENV_AUTH \
    -e RCLONE_CONFIG_ARCHIVE_ENDPOINT \
    -e RCLONE_CONFIG_ARCHIVE_REGION \
    -e RCLONE_CONFIG_ARCHIVE_ACL \
    -e AWS_ACCESS_KEY_ID \
    -e AWS_SECRET_ACCESS_KEY \
    -e AWS_SESSION_TOKEN \
    "$RCLONE_IMAGE" "${RCLONE_CA_CLI_ARGS[@]}" copyto /transfer/item "$remote" --immutable --retries 1 --low-level-retries 1
}

rclone_download_bounded() {
  remote="$1"
  local_file="$2"
  max_bytes="$3"
  label="$4"
  require_byte_cap "$max_bytes" "$label byte cap"
  set +e
  rclone_docker cat "$remote" | head -c "$((max_bytes + 1))" > "$local_file"
  transfer_status=("${PIPESTATUS[@]}")
  set -e
  actual_bytes="$(wc -c < "$local_file" | tr -d '[:space:]')"
  require_uint "$actual_bytes" "$label bytes"
  [ "$actual_bytes" -le "$max_bytes" ] || die "$label exceeds its transfer byte cap"
  [ "${transfer_status[0]}" -eq 0 ] && [ "${transfer_status[1]}" -eq 0 ] \
    || die "$label transfer failed before its complete bounded payload was received"
}

pg_docker() {
  tool="$1"
  shift
  case "$tool" in
    psql|pg_dump) ;;
    *) die "unsupported PostgreSQL client tool" ;;
  esac
  pg_docker_run --rm -i \
      -e PGHOST -e PGPORT -e PGDATABASE -e PGUSER -e PGPASSWORD -e PGSSLMODE -e PGSSLROOTCERT \
      --cap-drop ALL --security-opt no-new-privileges \
      --entrypoint "$tool" "$PG_CLIENT_IMAGE" "$@"
}

database_target_identity() {
  identity="$(pg_docker psql -X -tA -v ON_ERROR_STOP=1 -c \
    "select control.system_identifier || ':' || database.oid from pg_control_system() control cross join pg_database database where database.datname=current_database()" \
    | tr -d '[:space:]')"
  printf '%s' "$identity" | grep -Eq '^[0-9]{1,24}:[0-9]{1,10}$' \
    || die "database did not return a stable system/database identity"
  printf '%s\n' "$identity"
}

pg_dump_scoped() {
  expected_identity="$1"
  scope_work_dir="$2"
  printf '%s' "$expected_identity" | grep -Eq '^[0-9]{1,24}:[0-9]{1,10}$' \
    || die "expected snapshot database identity is malformed"
  controller_sql="$scope_work_dir/dump-controller.sql"
  {
    cat <<'SQL'
\set ON_ERROR_STOP on
begin isolation level repeatable read read only;
do $guard$
declare actual_identity text;
begin
  select control.system_identifier || ':' || database.oid
    into actual_identity
    from pg_control_system() control
    cross join pg_database database
    where database.datname = current_database();
SQL
    printf "  if actual_identity is distinct from '%s' then\n" "$expected_identity"
    cat <<'SQL'
    raise exception 'snapshot database identity changed on the exporting connection';
  end if;
end
$guard$;
\o /scope/exported-snapshot.tmp
select pg_export_snapshot();
\o
\! mv /scope/exported-snapshot.tmp /scope/exported-snapshot
select pg_sleep(900);
SQL
  } > "$controller_sql"
  pg_docker_run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
    -e PGHOST -e PGPORT -e PGDATABASE -e PGUSER -e PGPASSWORD -e PGSSLMODE -e PGSSLROOTCERT \
    -v "$scope_work_dir:/scope" --entrypoint sh "$PG_CLIENT_IMAGE" -eu -c '
      set +x
      rm -f /scope/exported-snapshot /scope/exported-snapshot.tmp /scope/dump-controller.log
      psql -X -tA -v ON_ERROR_STOP=1 -f /scope/dump-controller.sql >/scope/dump-controller.log 2>&1 &
      controller_pid=$!
      cleanup_controller() {
        kill "$controller_pid" >/dev/null 2>&1 || true
        wait "$controller_pid" >/dev/null 2>&1 || true
      }
      trap cleanup_controller EXIT HUP INT TERM
      attempt=0
      while [ ! -s /scope/exported-snapshot ]; do
        if ! kill -0 "$controller_pid" >/dev/null 2>&1; then
          printf "snapshot identity controller exited before export\n" >&2
          tail -n 20 /scope/dump-controller.log >&2 || true
          exit 1
        fi
        attempt=$((attempt + 1))
        [ "$attempt" -le 300 ] || { printf "snapshot identity controller timed out\n" >&2; exit 1; }
        sleep 0.1
      done
      exported_snapshot="$(tr -d "[:space:]" < /scope/exported-snapshot)"
      printf "%s" "$exported_snapshot" | grep -Eq "^[0-9A-Fa-f-]{5,128}$" \
        || { printf "exported snapshot identifier is malformed\n" >&2; exit 1; }
      pg_dump --format=custom --schema=public --no-owner --no-privileges \
        --exclude-extension="*" --snapshot="$exported_snapshot"
    '
}

snapshot_name() {
  environment="$1"
  revision="$2"
  expires_at="$3"
  nonce="$4"
  suffix="${5:-}"
  short_revision="$(printf '%s' "$revision" | cut -c1-12)"
  [ "$short_revision" != "unknown" ] || short_revision=0000000
  printf 'fsdb-%s-%s-%s-%s%s.dump\n' "$environment" "$expires_at" "$short_revision" "$nonce" "$suffix"
}

print_plan() {
  plan="$1"
  scope="$2"
  printf '%s\n' "$plan"
  printf 'scope_sha256=%s\n' "$scope"
}

verify_fresh_authorization() {
  operation="$1"
  scope="$2"
  authorization_id="$3"
  approved_scope="$4"
  expires_at="$5"
  intent_reference="$6"

  require_safe_id "$authorization_id" "authorization id"
  [ "${#authorization_id}" -ge 16 ] || die "authorization id must be at least 16 characters and one-use"
  require_sha256 "$approved_scope" "approved scope"
  [ "$approved_scope" = "$scope" ] || die "approved scope does not match the current plan; review the new dry-run"
  require_uint "$expires_at" "approval expiry"

  current_time="$(now_epoch)"
  [ "$expires_at" -ge "$current_time" ] || die "owner authorization is stale"
  [ "$expires_at" -le $((current_time + CLOUD_DB_APPROVAL_MAX_TTL_SECONDS)) ] \
    || die "owner authorization exceeds the 15-minute freshness window"
  require_snapshot_name "$intent_reference"

  signature="${CLOUD_DB_AUTHORIZATION_SIGNATURE:-}"
  [ -n "$signature" ] || die "CLOUD_DB_AUTHORIZATION_SIGNATURE is required"
  printf '%s' "$signature" | grep -Eq '^[A-Za-z0-9+/=]{80,16384}$' \
    || die "authorization signature must be bounded base64"

  ensure_recovery_state_dir
  state_dir="$RECOVERY_STATE_DIR"
  verification_dir="$(mktemp -d "$state_dir/verify.XXXXXX")"
  authorization_message="$verification_dir/authorization.txt"
  authorization_signature="$verification_dir/authorization.sig"
  {
    printf 'format=firestarter-cloud-db-authorization-v1\n'
    printf 'operation=%s\n' "$operation"
    printf 'scope_sha256=%s\n' "$scope"
    printf 'authorization_id=%s\n' "$authorization_id"
    printf 'expires_at=%s\n' "$expires_at"
    printf 'reference=%s\n' "$intent_reference"
  } > "$authorization_message"
  if ! printf '%s' "$signature" \
    | docker_run --rm -i --network none --read-only --cap-drop ALL \
        --security-opt no-new-privileges "$OPENSSL_IMAGE" base64 -d -A \
        > "$authorization_signature"; then
    rm -rf "$verification_dir"
    die "authorization signature is not valid base64"
  fi
  public_key_mount="$authorization_public_key:/authorization/public.pem:ro"
  message_mount="$authorization_message:/authorization/message:ro"
  signature_mount="$authorization_signature:/authorization/signature:ro"
  if ! docker_run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
    -v "$public_key_mount" -v "$message_mount" -v "$signature_mount" \
    "$OPENSSL_IMAGE" dgst -sha256 -verify /authorization/public.pem \
      -signature /authorization/signature /authorization/message >/dev/null 2>&1; then
    rm -rf "$verification_dir"
    die "authorization signature was not made by the committed owner key"
  fi
  rm -rf "$verification_dir"

  authorization_key="$(sha256_text "$authorization_id")"
  authorization_dir="$state_dir/used-$authorization_key"
  if ! mkdir "$authorization_dir" 2>/dev/null; then
    die "authorization was already consumed locally; reconcile before requesting a new one"
  fi
  intent_tmp="$authorization_dir/intent.tmp"
  {
    printf 'format=firestarter-cloud-db-intent-v1\n'
    printf 'operation=%s\n' "$operation"
    printf 'reference=%s\n' "$intent_reference"
    printf 'scope_sha256=%s\n' "$scope"
    printf 'authorization_id_sha256=%s\n' "$authorization_key"
    printf 'target_id_sha256=%s\n' "$(sha256_text "$CLOUD_DB_TARGET_ID")"
    printf 'archive_id_sha256=%s\n' "$(sha256_text "$CLOUD_DB_ARCHIVE_ID")"
    printf 'consumed_at=%s\n' "$current_time"
  } > "$intent_tmp" || die "authorization consumed but write-ahead intent failed; outcome is indeterminate"
  mv "$intent_tmp" "$authorization_dir/intent" \
    || die "authorization consumed but write-ahead intent commit failed; outcome is indeterminate"
  ACTIVE_AUTHORIZATION_DIR="$authorization_dir"
}

record_outcome() {
  status="$1"
  detail="$2"
  require_safe_id "$status" "outcome status"
  require_safe_id "$detail" "outcome detail"
  outcome_tmp="$ACTIVE_AUTHORIZATION_DIR/outcome.tmp"
  {
    printf 'format=firestarter-cloud-db-outcome-v1\n'
    printf 'status=%s\n' "$status"
    printf 'detail=%s\n' "$detail"
    printf 'observed_at=%s\n' "$(now_epoch)"
  } > "$outcome_tmp" || die "provider outcome may exist but outcome journal failed; treat as indeterminate"
  mv "$outcome_tmp" "$ACTIVE_AUTHORIZATION_DIR/outcome" \
    || die "provider outcome may exist but outcome journal commit failed; treat as indeterminate"
}

manifest_value() {
  key="$1"
  file="$2"
  awk -F= -v wanted="$key" '
    $1 == wanted {
      if (seen) exit 3
      print substr($0, length($1) + 2)
      seen = 1
    }
    END { if (!seen) exit 2 }
  ' "$file"
}

validate_manifest_shape() {
  file="$1"
  awk -F= '
    NF != 2 { exit 2 }
    !($1 ~ /^(format|snapshot|environment|source_target_id|source_database_sha256|database_tls_sha256|archive_id|archive_config_sha256|connection_mode|schema|created_at|source_revision|migration_set_sha256|server_version_num|pg_client_image|bytes|sha256|reason)$/) { exit 3 }
    seen[$1]++ > 0 { exit 4 }
    END {
      required = "format snapshot environment source_target_id source_database_sha256 database_tls_sha256 archive_id archive_config_sha256 connection_mode schema created_at source_revision migration_set_sha256 server_version_num pg_client_image bytes sha256 reason"
      count = split(required, names, " ")
      for (i = 1; i <= count; i++) if (!seen[names[i]]) exit 5
    }
  ' "$file" || die "snapshot manifest is malformed or has unknown/duplicate fields"
}

create_snapshot() {
  object_name="$1"
  environment="$2"
  reason="$3"
  max_bytes="$4"
  work_dir="$5"
  revision="$6"
  migration_digest="$7"
  expected_database_sha256="$8"
  expected_database_identity="$9"

  require_snapshot_name "$object_name"
  require_safe_id "$environment" "environment"
  require_safe_id "$reason" "snapshot reason"
  require_byte_cap "$max_bytes" "maximum snapshot bytes"
  require_database_access
  require_archive_access
  require_source_binding "$revision" "$migration_digest"
  database_target_identity="$(database_target_identity)"
  [ "$database_target_identity" = "$expected_database_identity" ] \
    || die "database target changed after the reviewed plan"
  database_target_sha256="$(sha256_text "$database_target_identity")"
  require_sha256 "$database_target_sha256" "source database identity"
  [ "$database_target_sha256" = "$expected_database_sha256" ] \
    || die "database target changed after the reviewed plan"
  server_version_num="$(pg_docker psql -X -tA -v ON_ERROR_STOP=1 -c 'show server_version_num' | tr -d '[:space:]')"
  require_uint "$server_version_num" "database server version"
  server_major=$((server_version_num / 10000))
  [ "$server_major" -le 17 ] \
    || die "database server is newer than the pinned pg_dump client; update and review the image pin"

  dump_file="$work_dir/$object_name"
  manifest_file="$work_dir/${object_name%.dump}.manifest"
  ready_file="$work_dir/${object_name%.dump}.ready"
  dump_remote="$(archive_object "$object_name")"
  manifest_remote="$(archive_object "${object_name%.dump}.manifest")"
  ready_remote="$(archive_object "${object_name%.dump}.ready")"

  remote_listing="$(rclone_docker lsf "$(archive_dir)" --files-only --max-depth 1)" \
    || die "archive inventory is unreadable; refusing an overwrite-ambiguous upload"
  for remote_name in "$object_name" "${object_name%.dump}.manifest" "${object_name%.dump}.ready"; do
    if printf '%s\n' "$remote_listing" | grep -Fxq "$remote_name"; then
      die "snapshot object already exists; refusing to overwrite immutable recovery evidence"
    fi
  done

  say "Capturing app-owned schema ($CLOUD_DB_SCHEMA)"
  set +e
  pg_dump_scoped "$expected_database_identity" "$work_dir" \
    | head -c "$((max_bytes + 1))" > "$dump_file"
  capture_status=("${PIPESTATUS[@]}")
  set -e
  bytes="$(wc -c < "$dump_file" | tr -d '[:space:]')"
  require_uint "$bytes" "snapshot bytes"
  [ "$bytes" -le "$max_bytes" ] \
    || die "snapshot exceeded the owner-reviewed cap during capture; nothing was uploaded"
  [ "${capture_status[0]}" -eq 0 ] && [ "${capture_status[1]}" -eq 0 ] \
    || die "pg_dump failed before a complete bounded archive was captured; nothing was uploaded"
  [ -s "$dump_file" ] || die "pg_dump produced an empty archive"

  docker_run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges -v "$dump_file:/snapshot.dump:ro" "$PG_CLIENT_IMAGE" \
    pg_restore --list /snapshot.dump >/dev/null \
    || die "pg_restore could not read the newly-created archive"

  digest="$(sha256_file "$dump_file")"
  created_at="$(now_epoch)"

  {
    printf 'format=firestarter-cloud-db-snapshot-v1\n'
    printf 'snapshot=%s\n' "$object_name"
    printf 'environment=%s\n' "$environment"
    printf 'source_target_id=%s\n' "$CLOUD_DB_TARGET_ID"
    printf 'source_database_sha256=%s\n' "$database_target_sha256"
    printf 'database_tls_sha256=%s\n' "$(database_tls_digest)"
    printf 'archive_id=%s\n' "$CLOUD_DB_ARCHIVE_ID"
    printf 'archive_config_sha256=%s\n' "$(archive_config_digest)"
    printf 'connection_mode=%s\n' "$CLOUD_DB_CONNECTION_MODE"
    printf 'schema=%s\n' "$CLOUD_DB_SCHEMA"
    printf 'created_at=%s\n' "$created_at"
    printf 'source_revision=%s\n' "$revision"
    printf 'migration_set_sha256=%s\n' "$migration_digest"
    printf 'server_version_num=%s\n' "$server_version_num"
    printf 'pg_client_image=%s\n' "$PG_CLIENT_IMAGE"
    printf 'bytes=%s\n' "$bytes"
    printf 'sha256=%s\n' "$digest"
    printf 'reason=%s\n' "$reason"
  } > "$manifest_file"

  say "Publishing immutable archive, manifest, and readiness marker"
  rclone_upload "$dump_file" "$dump_remote" \
    || die "archive upload failed; authorization is consumed and the remote outcome must be reconciled"
  remote_proof_file="$work_dir/${object_name%.dump}.remote-proof"
  rclone_download_bounded "$dump_remote" "$remote_proof_file" "$max_bytes" "uploaded archive proof"
  remote_digest="$(sha256_file "$remote_proof_file")"
  rm -f "$remote_proof_file"
  [ "$remote_digest" = "$digest" ] \
    || die "uploaded archive checksum mismatch; snapshot is not ready"
  rclone_upload "$manifest_file" "$manifest_remote" \
    || die "manifest upload failed; snapshot is not ready and must be reconciled"
  manifest_digest="$(sha256_file "$manifest_file")"
  remote_manifest_file="$work_dir/${object_name%.dump}.remote-manifest"
  rclone_download_bounded "$manifest_remote" "$remote_manifest_file" 16384 "uploaded manifest proof"
  remote_manifest_digest="$(sha256_file "$remote_manifest_file")"
  rm -f "$remote_manifest_file"
  [ "$remote_manifest_digest" = "$manifest_digest" ] \
    || die "uploaded manifest checksum mismatch; snapshot is not ready"
  {
    printf 'archive_sha256=%s\n' "$digest"
    printf 'manifest_sha256=%s\n' "$manifest_digest"
  } > "$ready_file"
  rclone_upload "$ready_file" "$ready_remote" \
    || die "readiness marker upload failed; snapshot remains unpublished"
  ready_digest="$(sha256_file "$ready_file")"
  remote_ready_file="$work_dir/${object_name%.dump}.remote-ready"
  rclone_download_bounded "$ready_remote" "$remote_ready_file" 1024 "uploaded readiness-marker proof"
  remote_ready_digest="$(sha256_file "$remote_ready_file")"
  rm -f "$remote_ready_file"
  [ "$remote_ready_digest" = "$ready_digest" ] \
    || die "uploaded readiness marker checksum mismatch; snapshot is not ready"

  CREATED_SNAPSHOT_NAME="$object_name"
  CREATED_SNAPSHOT_SHA256="$digest"
  CREATED_SNAPSHOT_BYTES="$bytes"
  note "Snapshot ready: $object_name ($bytes bytes, checksum verified)"
}

fetch_snapshot_evidence() {
  object_name="$1"
  work_dir="$2"
  require_snapshot_name "$object_name"
  manifest_file="$work_dir/${object_name%.dump}.manifest"
  ready_file="$work_dir/${object_name%.dump}.ready"
  rclone_download_bounded "$(archive_object "${object_name%.dump}.ready")" "$ready_file" 1024 "snapshot readiness marker"
  rclone_download_bounded "$(archive_object "${object_name%.dump}.manifest")" "$manifest_file" 16384 "snapshot manifest"
  validate_manifest_shape "$manifest_file"
  awk -F= '
    NF != 2 { exit 2 }
    !($1 ~ /^(archive_sha256|manifest_sha256)$/) { exit 3 }
    seen[$1]++ > 0 { exit 4 }
    END { if (!seen["archive_sha256"] || !seen["manifest_sha256"]) exit 5 }
  ' "$ready_file" || die "snapshot readiness marker is malformed"
  [ "$(manifest_value format "$manifest_file")" = "firestarter-cloud-db-snapshot-v1" ] \
    || die "unsupported snapshot manifest format"
  [ "$(manifest_value snapshot "$manifest_file")" = "$object_name" ] \
    || die "snapshot manifest is bound to a different object"
  [ "$(manifest_value archive_id "$manifest_file")" = "$CLOUD_DB_ARCHIVE_ID" ] \
    || die "snapshot manifest archive identity mismatch"
  [ "$(manifest_value archive_config_sha256 "$manifest_file")" = "$(archive_config_digest)" ] \
    || die "snapshot manifest archive configuration mismatch"
  [ "$(manifest_value schema "$manifest_file")" = "$CLOUD_DB_SCHEMA" ] \
    || die "snapshot scope is not the reviewed app-owned schema"
  manifest_digest="$(manifest_value sha256 "$manifest_file")"
  ready_digest="$(manifest_value archive_sha256 "$ready_file")"
  ready_manifest_digest="$(manifest_value manifest_sha256 "$ready_file")"
  require_sha256 "$manifest_digest" "manifest archive checksum"
  require_sha256 "$ready_digest" "readiness checksum"
  require_sha256 "$ready_manifest_digest" "readiness manifest checksum"
  [ "$manifest_digest" = "$ready_digest" ] || die "readiness marker and manifest disagree"
  [ "$(sha256_file "$manifest_file")" = "$ready_manifest_digest" ] \
    || die "readiness marker is not bound to the downloaded manifest"
  FETCHED_MANIFEST_FILE="$manifest_file"
  FETCHED_SNAPSHOT_SHA256="$manifest_digest"
  FETCHED_SNAPSHOT_BYTES="$(manifest_value bytes "$manifest_file")"
  require_uint "$FETCHED_SNAPSHOT_BYTES" "manifest snapshot bytes"
}

download_and_verify_snapshot() {
  object_name="$1"
  work_dir="$2"
  max_bytes="$3"
  require_byte_cap "$max_bytes" "maximum snapshot bytes"
  [ "$FETCHED_SNAPSHOT_BYTES" -le "$max_bytes" ] \
    || die "snapshot exceeds the owner-reviewed byte cap"
  dump_file="$work_dir/$object_name"
  rclone_download_bounded "$(archive_object "$object_name")" "$dump_file" "$max_bytes" "snapshot archive"
  [ -s "$dump_file" ] || die "downloaded snapshot archive is empty"
  actual_bytes="$(wc -c < "$dump_file" | tr -d '[:space:]')"
  [ "$actual_bytes" = "$FETCHED_SNAPSHOT_BYTES" ] || die "snapshot byte count does not match its manifest"
  actual_digest="$(sha256_file "$dump_file")"
  [ "$actual_digest" = "$FETCHED_SNAPSHOT_SHA256" ] || die "snapshot checksum verification failed"
  docker_run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges -v "$dump_file:/snapshot.dump:ro" "$PG_CLIENT_IMAGE" \
    pg_restore --list /snapshot.dump >/dev/null || die "snapshot archive is unreadable"
  VERIFIED_SNAPSHOT_FILE="$dump_file"
}
