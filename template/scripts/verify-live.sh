#!/usr/bin/env bash
# Verify the artifact a collaborator can actually fetch, not the local build.
# Deliberately curl+bash only: this runs after deploy, without a host SDK.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/verify-live.sh --expect BUILD_ID [options] BASE_URL [BASE_URL ...]

Poll every BASE_URL until the same expected build is visible at each one.

Options:
  --path PATH       Probe path (default: /health)
  --field NAME      JSON provenance field (default: git_sha)
  --contains        Match BUILD_ID literally in the response instead of a JSON field
  --range PATH|URL  After convergence, require a byte-range response (206)
  --attempts N      Maximum propagation attempts (default: 30)
  --interval N      Seconds between attempts (default: 10)
  --timeout N       Per-request timeout in seconds (default: 40)
  -h, --help        Show this help

Examples:
  scripts/verify-live.sh --expect "$(git rev-parse --short HEAD)" https://app.example.test
  scripts/verify-live.sh --expect build-42 --contains --path / https://a.example.test https://origin.example.test
  scripts/verify-live.sh --expect build-42 --contains --path / --range /media/demo.mp4 https://app.example.test
EOF
}

die() {
  printf 'verify-live: %s\n' "$*" >&2
  exit 2
}

join_url() {
  local base=${1%/}
  local suffix=$2
  case "$suffix" in
    http://*|https://*) printf '%s' "$suffix" ;;
    /*) printf '%s%s' "$base" "$suffix" ;;
    *) printf '%s/%s' "$base" "$suffix" ;;
  esac
}

cache_bust() {
  case "$1" in
    *\?*) printf '%s&firestarter_verify=%s' "$1" "$2" ;;
    *) printf '%s?firestarter_verify=%s' "$1" "$2" ;;
  esac
}

display_origin() {
  local url=${1%%\?*}
  url=${url%%\#*}
  local scheme=${url%%://*}
  local rest=${url#*://}
  local authority=${rest%%/*}
  authority=${authority##*@}
  printf '%s://%s' "$scheme" "$authority"
}

positive_integer() {
  case "$2" in
    ''|*[!0-9]*|0) die "$1 must be a positive integer" ;;
  esac
}

expect=''
probe_path='/health'
json_field='git_sha'
match_mode='json'
range_target=''
attempts=30
interval=10
timeout=40

while [ "$#" -gt 0 ]; do
  case "$1" in
    --expect) [ "$#" -ge 2 ] || die '--expect needs a value'; expect=$2; shift 2 ;;
    --path) [ "$#" -ge 2 ] || die '--path needs a value'; probe_path=$2; shift 2 ;;
    --field) [ "$#" -ge 2 ] || die '--field needs a value'; json_field=$2; shift 2 ;;
    --contains) match_mode='contains'; shift ;;
    --range) [ "$#" -ge 2 ] || die '--range needs a value'; range_target=$2; shift 2 ;;
    --attempts) [ "$#" -ge 2 ] || die '--attempts needs a value'; attempts=$2; shift 2 ;;
    --interval) [ "$#" -ge 2 ] || die '--interval needs a value'; interval=$2; shift 2 ;;
    --timeout) [ "$#" -ge 2 ] || die '--timeout needs a value'; timeout=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --) shift; break ;;
    -*) die "unknown option: $1" ;;
    *) break ;;
  esac
done

[ -n "$expect" ] || die '--expect is required and must not be empty'
[ "$#" -gt 0 ] || die 'at least one BASE_URL is required'
case "$expect" in *[!A-Za-z0-9._:-]*) die 'BUILD_ID may contain only A-Z, a-z, 0-9, dot, underscore, colon, and dash' ;; esac
case "$json_field" in ''|*[!A-Za-z0-9_.-]*) die 'field name contains unsupported characters' ;; esac
case "$probe_path" in /*) ;; *) die '--path must be relative to each BASE_URL and start with /' ;; esac
positive_integer attempts "$attempts"
positive_integer timeout "$timeout"
case "$interval" in ''|*[!0-9]*) die 'interval must be a non-negative integer' ;; esac
command -v curl >/dev/null 2>&1 || die 'curl is required'
for base in "$@"; do
  case "$base" in http://*|https://*) ;; *) die 'every BASE_URL must use http:// or https://' ;; esac
  case "$base" in *\?*|*\#*) die 'BASE_URL must not contain a query or fragment; put a query on --path' ;; esac
  authority=${base#*://}
  authority=${authority%%/*}
  case "$authority" in *@*) die 'credentials in BASE_URL are forbidden' ;; esac
done

tmp_dir=$(mktemp -d 2>/dev/null || mktemp -d -t verify-live)
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM
user_agent='Mozilla/5.0 (compatible; firestarter-live-verifier/1.0)'

probe_one() {
  local base=$1
  local attempt=$2
  local body="$tmp_dir/body"
  local compact="$tmp_dir/compact"
  local headers="$tmp_dir/headers"
  local status
  local url
  url=$(cache_bust "$(join_url "$base" "$probe_path")" "$attempt")
  if ! status=$(curl --silent --max-time "$timeout" --max-filesize 5242880 \
      --user-agent "$user_agent" --header 'Cache-Control: no-cache' \
      --dump-header "$headers" --output "$body" --write-out '%{http_code}' "$url"); then
    printf 'transport error' >&2
    return 1
  fi
  [ "$status" = '200' ] || { printf 'HTTP %s' "$status" >&2; return 1; }

  if [ "$match_mode" = 'contains' ]; then
    grep -Fq -- "$expect" "$body" || { printf 'expected build absent' >&2; return 1; }
  else
    grep -Eiq '^Content-Type:[[:space:]]*application/([A-Za-z0-9.+-]*\+)?json([[:space:]]*;|[[:space:]]*$)' "$headers" || {
      printf 'provenance response was not JSON' >&2
      return 1
    }
    tr -d '[:space:]' < "$body" > "$compact"
    grep -Fq -- "\"$json_field\":\"$expect\"" "$compact" || {
      printf 'field %s did not equal expected build' "$json_field" >&2
      return 1
    }
  fi
}

converged=0
attempt=1
while [ "$attempt" -le "$attempts" ]; do
  all_green=1
  for base in "$@"; do
    detail="$tmp_dir/detail"
    : > "$detail"
    if probe_one "$base" "$attempt" 2> "$detail"; then
      printf 'PASS  %s serves %s\n' "$(display_origin "$base")" "$expect"
    else
      all_green=0
      printf 'WAIT  %s (%s)\n' "$(display_origin "$base")" "$(cat "$detail")" >&2
    fi
  done
  if [ "$all_green" -eq 1 ]; then
    converged=1
    break
  fi
  [ "$attempt" -eq "$attempts" ] || sleep "$interval"
  attempt=$((attempt + 1))
done

[ "$converged" -eq 1 ] || {
  printf 'verify-live: deployment did not converge on %s across every hostname after %s attempts\n' "$expect" "$attempts" >&2
  exit 1
}

check_range() {
  local target=$1
  local headers="$tmp_dir/range-headers"
  local status
  if ! status=$(curl --silent --max-time "$timeout" --max-filesize 1048576 \
      --user-agent "$user_agent" --header 'Cache-Control: no-cache' \
      --header 'Range: bytes=1-2' --dump-header "$headers" \
      --output /dev/null --write-out '%{http_code}' "$target"); then
    printf 'verify-live: range probe transport failure: %s\n' "$target" >&2
    return 1
  fi
  if [ "$status" != '206' ] || ! grep -Eiq '^Content-Range:[[:space:]]*bytes[[:space:]]+1-2/' "$headers"; then
    printf 'verify-live: range probe failed for %s (expected 206 + Content-Range, got %s)\n' "$(display_origin "$target")" "$status" >&2
    return 1
  fi
  printf 'PASS  %s honors byte ranges\n' "$(display_origin "$target")"
}

if [ -n "$range_target" ]; then
  case "$range_target" in
    http://*|https://*) check_range "$range_target" ;;
    *) for base in "$@"; do check_range "$(join_url "$base" "$range_target")"; done ;;
  esac
fi

printf 'verify-live: deployed artifact verified across %s hostname(s)\n' "$#"
