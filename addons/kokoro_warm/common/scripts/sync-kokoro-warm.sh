#!/usr/bin/env bash
# Keep the kokoro_warm narration audio component in sync with project-firestarter.
#
# The spec + reader + master + guard + generator are MAINTAINED in
# project-firestarter (addons/kokoro_warm/common/scripts). This script re-pulls
# them so a project that adopted the add-on stays on the shared standard instead
# of silently forking it, and records the source commit in .upstream-sha.
#
#   scripts/sync-kokoro-warm.sh          # refresh from firestarter master
#   scripts/sync-kokoro-warm.sh --check  # fail if this copy has drifted (CI use)
#
# The component files are expected to live in this script's own directory; set
# KOKORO_WARM_DIR to override (e.g. if you vendored them into a subdirectory).
# Source is a local firestarter checkout ($FIRESTARTER_DIR) when set, else a
# shallow clone of $FIRESTARTER_REPO at $FIRESTARTER_REF.
set -euo pipefail

FIRESTARTER_REPO="${FIRESTARTER_REPO:-https://github.com/pulkitsinghal/project-firestarter}"
FIRESTARTER_REF="${FIRESTARTER_REF:-master}"
ADDON_REL="addons/kokoro_warm/common/scripts"
FILES=(narration-audio.spec.json narration-spec.sh master-narration-audio.sh check-narration-audio.sh render-narration.sh)

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VDIR="${KOKORO_WARM_DIR:-$HERE}"
mode="${1:-sync}"

tmp=""
# Keep cleanup status-neutral: a bare `[[ -n "" ]] && …` in an EXIT trap returns
# non-zero and would corrupt the script's exit code (a false "drift" on success).
cleanup() { [[ -n "$tmp" ]] && rm -rf "$tmp"; return 0; }
trap cleanup EXIT

if [[ -n "${FIRESTARTER_DIR:-}" ]] && git -C "$FIRESTARTER_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  git -C "$FIRESTARTER_DIR" fetch --quiet origin "$FIRESTARTER_REF" 2>/dev/null || true
  src_sha="$(git -C "$FIRESTARTER_DIR" rev-parse "origin/$FIRESTARTER_REF" 2>/dev/null || git -C "$FIRESTARTER_DIR" rev-parse "$FIRESTARTER_REF")"
  get() { git -C "$FIRESTARTER_DIR" show "$src_sha:$ADDON_REL/$1"; }
else
  command -v git >/dev/null || { echo "git is required" >&2; exit 69; }
  tmp="$(mktemp -d)"
  echo "cloning $FIRESTARTER_REPO@$FIRESTARTER_REF ..." >&2
  git clone --quiet --depth 1 --branch "$FIRESTARTER_REF" "$FIRESTARTER_REPO" "$tmp" 2>/dev/null \
    || { echo "clone failed; set FIRESTARTER_DIR to a local checkout" >&2; exit 1; }
  src_sha="$(git -C "$tmp" rev-parse HEAD)"
  get() { cat "$tmp/$ADDON_REL/$1"; }
fi

if [[ "$mode" == "--check" ]]; then
  drift=0
  for f in "${FILES[@]}"; do
    if ! diff -q <(get "$f") "$VDIR/$f" >/dev/null 2>&1; then
      echo "DRIFT: $f differs from firestarter@$src_sha" >&2
      drift=1
    fi
  done
  if [[ $drift -ne 0 ]]; then
    echo "kokoro_warm has drifted from upstream — re-run: scripts/sync-kokoro-warm.sh" >&2
    exit 1
  fi
  echo "kokoro_warm matches firestarter@$src_sha ✓"
  exit 0
fi

mkdir -p "$VDIR"
for f in "${FILES[@]}"; do
  get "$f" > "$VDIR/$f"
  case "$f" in *.sh) chmod +x "$VDIR/$f";; esac
  echo "  synced $f"
done
printf '%s\n' "$src_sha" > "$VDIR/.upstream-sha"
echo "kokoro_warm synced from $FIRESTARTER_REPO@$FIRESTARTER_REF ($src_sha)"
