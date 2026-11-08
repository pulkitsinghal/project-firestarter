#!/usr/bin/env bash
# Honest receipts for local producer->consumer work: "queued is not accepted".
#
# A local feature must not tell the user its work is "queued" unless a real
# worker or a durable handoff has actually accepted it. If the consumer, worker,
# or connector is absent, the honest receipt is "blocked" (or "no-op" when there
# was nothing to do) -- never "queued", which claims the work is on its way when
# nothing will carry it.
#
# The danger is not only the wrong word. If the producer also consumes the
# item's idempotency / "requested" marker while claiming queued, a later retry is
# skipped once the consumer appears, so the work is silently dropped. So a
# blocked receipt keeps the item retryable and does NOT consume its requested
# marker, and the later retry runs once when the worker is there.
#
# This is the generic, stack-neutral reference. It is pure: enum state in, one
# honest receipt out, no I/O, no state, no payload echo (its only inputs are
# non-sensitive enum tokens), so a local pipeline can wire it straight into its
# acknowledgement path and its tests. A missing load-bearing flag is an error,
# never a permissive default.
#
#   receipt    requested  retryable  meaning
#   no-op      false      false      nothing to do (no work item)
#   blocked    false      true       work exists, no consumer accepted it
#   queued     true       true       accepted by a worker/durable handoff, not started
#   partial    true       true       accepted; some but not all done
#   completed  true       false      accepted and fully done
#
# Exit codes:
#   0  classify printed an honest receipt, or check confirmed the claim is honest
#   1  check found the claimed receipt dishonest (it overstates reality)
#   2  usage / invalid input

set -uo pipefail
export LC_ALL=C

usage() {
  cat >&2 <<'USAGE'
usage:
  work-receipt.sh classify --item <yes|no> --consumer <present|absent> \
                           --handoff <durable|none> --progress <none|some|all>
  work-receipt.sh check --claim <no-op|blocked|queued|partial|completed> \
                        --item <yes|no> --consumer <present|absent> \
                        --handoff <durable|none> --progress <none|some|all> \
                        [--requested <true|false>] [--retryable <true|false>]
USAGE
}

fail() { # invalid usage/input -> exit 2
  echo "work-receipt: ERROR code=$1" >&2
  usage
  exit 2
}

in_set() { # in_set value allowed...
  _needle=$1
  shift
  for _candidate in "$@"; do
    [ "$_needle" = "$_candidate" ] && return 0
  done
  return 1
}

# honest_receipt item consumer handoff progress -> "<receipt> <requested> <retryable>"
honest_receipt() {
  _item=$1
  _consumer=$2
  _handoff=$3
  _progress=$4
  if [ "$_item" = no ]; then
    printf '%s %s %s\n' no-op false false
    return 0
  fi
  # A work item exists. It is accepted only by a real worker or a durable handoff.
  if [ "$_consumer" = present ] || [ "$_handoff" = durable ]; then
    case "$_progress" in
      none) printf '%s %s %s\n' queued true true ;;
      some) printf '%s %s %s\n' partial true true ;;
      all) printf '%s %s %s\n' completed true false ;;
    esac
    return 0
  fi
  # Not accepted: queued is NOT accepted. Stay blocked, keep the request
  # unconsumed, and leave the item retryable so a later attempt still runs.
  printf '%s %s %s\n' blocked false true
  return 0
}

cmd=${1:-}
case "$cmd" in
  classify | check) shift ;;
  "" | -h | --help) usage; exit 2 ;;
  *) fail "unknown-subcommand" ;;
esac

claim=""
item=""
consumer=""
handoff=""
progress=""
requested_claim=""
retryable_claim=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --claim) [ "$#" -ge 2 ] || fail "missing-value"; claim=$2; shift 2 ;;
    --item) [ "$#" -ge 2 ] || fail "missing-value"; item=$2; shift 2 ;;
    --consumer) [ "$#" -ge 2 ] || fail "missing-value"; consumer=$2; shift 2 ;;
    --handoff) [ "$#" -ge 2 ] || fail "missing-value"; handoff=$2; shift 2 ;;
    --progress) [ "$#" -ge 2 ] || fail "missing-value"; progress=$2; shift 2 ;;
    --requested) [ "$#" -ge 2 ] || fail "missing-value"; requested_claim=$2; shift 2 ;;
    --retryable) [ "$#" -ge 2 ] || fail "missing-value"; retryable_claim=$2; shift 2 ;;
    *) fail "unknown-flag" ;;
  esac
done

in_set "$item" yes no || fail "bad-item"
in_set "$consumer" present absent || fail "bad-consumer"
in_set "$handoff" durable none || fail "bad-handoff"
in_set "$progress" none some all || fail "bad-progress"

honest=$(honest_receipt "$item" "$consumer" "$handoff" "$progress")
receipt=${honest%% *}
rest=${honest#* }
requested=${rest%% *}
retryable=${rest##* }

if [ "$cmd" = classify ]; then
  printf '{"receipt":"%s","requested":%s,"retryable":%s}\n' \
    "$receipt" "$requested" "$retryable"
  exit 0
fi

# check: compare the claimed receipt (and optional flag claims) to the honest one.
in_set "$claim" no-op blocked queued partial completed || fail "bad-claim"
mismatch=""
[ "$claim" = "$receipt" ] || mismatch="receipt"
if [ -n "$requested_claim" ]; then
  in_set "$requested_claim" true false || fail "bad-requested"
  [ "$requested_claim" = "$requested" ] || mismatch="${mismatch:+$mismatch,}requested"
fi
if [ -n "$retryable_claim" ]; then
  in_set "$retryable_claim" true false || fail "bad-retryable"
  [ "$retryable_claim" = "$retryable" ] || mismatch="${mismatch:+$mismatch,}retryable"
fi

if [ -n "$mismatch" ]; then
  printf 'DISHONEST claimed=%s honest=%s requested=%s retryable=%s mismatch=%s\n' \
    "$claim" "$receipt" "$requested" "$retryable" "$mismatch" >&2
  exit 1
fi
printf 'OK receipt=%s requested=%s retryable=%s\n' "$receipt" "$requested" "$retryable"
exit 0
