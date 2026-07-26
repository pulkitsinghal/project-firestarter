#!/usr/bin/env bash
# Shared reader for narration-audio.spec.json — the single source of the Warm
# Heart audio numbers. Sourced (not executed) by master-narration-audio.sh and
# check-help-audio.sh so the mastering target and the shipped-clip guard read
# the exact same values and cannot drift.
#
# No jq/python/node dependency: the spec is a flat JSON object of scalar values,
# read with a small grep/sed helper. Consumers call spec_get for each key and
# validate required keys themselves (see spec_require_vars), so a missing key
# fails loudly in the caller's shell rather than fail-open.

NARRATION_SPEC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NARRATION_SPEC_FILE="${NARRATION_SPEC_FILE:-$NARRATION_SPEC_DIR/narration-audio.spec.json}"
test -s "$NARRATION_SPEC_FILE" || { echo "narration spec missing: $NARRATION_SPEC_FILE" >&2; exit 70; }

# spec_get KEY -> the scalar value for "KEY" (surrounding quotes/space stripped),
# or empty if absent. Matches a quoted string OR a bare number up to the next
# comma / closing brace, so it handles both `"aacBitrate": "96k"` and
# `"sampleRate": 48000` / `"truePeakCeilingDbtp": -1.5`.
spec_get() {
  grep -oE "\"$1\"[[:space:]]*:[[:space:]]*(\"[^\"]*\"|[^,}[:space:]]+)" "$NARRATION_SPEC_FILE" \
    | head -1 \
    | sed -E 's/^"[^"]*"[[:space:]]*:[[:space:]]*//; s/^"//; s/"$//'
}

# spec_require_vars NAME=value ... -> exit 70 if any value is empty. Call it in
# the caller's shell (not a subshell) after reading keys with spec_get, e.g.:
#   SR="$(spec_get sampleRate)"; spec_require_vars "sampleRate=$SR"
spec_require_vars() {
  local pair key val
  for pair in "$@"; do
    key="${pair%%=*}"; val="${pair#*=}"
    if [[ -z "$val" ]]; then
      echo "narration spec: required key '$key' missing/empty in $NARRATION_SPEC_FILE" >&2
      exit 70
    fi
  done
}
