#!/usr/bin/env bash
# Guard: every shipped narrated clip must carry spec-compliant audio.
#
# Reads the SAME narration-audio.spec.json the masterer uses, then ffprobes each
# *.mp4 in the narrated-clips directory and fails if an audio-bearing clip is not
# the spec sample rate / channel count, or its decoded true peak exceeds the
# delivery ceiling (truePeakCeilingDbtp). This is the durable stop against audio
# drift — mixed sample rates or plosive-popping hot true peaks reaching users.
#
# Point it at your clips with the first argument or $NARRATION_VIDEO_DIR:
#   check-narration-audio.sh path/to/videos
#   NARRATION_VIDEO_DIR=public/help/videos check-narration-audio.sh
# Default: public/videos. A missing/empty directory is a pass (nothing to
# enforce yet) with a loud notice, so a freshly-stamped project is not red before
# it has any clips.
#
# Runs on the host / CI runner (needs ffprobe + ffmpeg). A missing ffprobe/ffmpeg
# is a hard error, never a silent pass.
set -euo pipefail

FF="${FFMPEG:-ffmpeg}"
FP="${FFPROBE:-ffprobe}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VIDEOS="${1:-${NARRATION_VIDEO_DIR:-public/videos}}"

command -v "$FP" >/dev/null 2>&1 || { echo "check-narration-audio: ffprobe is required (brew install ffmpeg / apt-get install ffmpeg)" >&2; exit 69; }
command -v "$FF" >/dev/null 2>&1 || { echo "check-narration-audio: ffmpeg is required (brew install ffmpeg / apt-get install ffmpeg)" >&2; exit 69; }

# shellcheck source=scripts/narration-spec.sh
source "$HERE/narration-spec.sh"
WANT_SR="$(spec_get sampleRate)"
WANT_CH="$(spec_get channels)"
CEIL_TP="$(spec_get truePeakCeilingDbtp)"
spec_require_vars "sampleRate=$WANT_SR" "channels=$WANT_CH" "truePeakCeilingDbtp=$CEIL_TP"

if [[ ! -d "$VIDEOS" ]]; then
  echo "check-narration-audio: no clips directory at '$VIDEOS' — nothing to check."
  echo "  (set NARRATION_VIDEO_DIR or pass a path once this project has narrated clips.)"
  exit 0
fi

shopt -s nullglob
clips=("$VIDEOS"/*.mp4)
if [[ ${#clips[@]} -eq 0 ]]; then
  echo "check-narration-audio: no .mp4 files in '$VIDEOS' — nothing to check."
  exit 0
fi

fail=0
checked=0
skipped=0
printf '%-30s %-8s %-4s %-9s %s\n' "clip" "rate" "ch" "peak/dBTP" "verdict"
printf '%-30s %-8s %-4s %-9s %s\n' "----" "----" "--" "---------" "-------"

for f in "${clips[@]}"; do
  b="$(basename "$f")"

  # A clip with no audio stream is a legitimately silent (non-narration) clip;
  # the spec governs audio when present, so note it and move on rather than fail.
  achan="$("$FP" -v error -select_streams a:0 -show_entries stream=channels -of csv=p=0 "$f" | head -1)"
  if [[ -z "$achan" ]]; then
    printf '%-30s %-8s %-4s %-9s %s\n' "$b" "-" "-" "-" "skip (silent)"
    skipped=$((skipped + 1))
    continue
  fi

  arate="$("$FP" -v error -select_streams a:0 -show_entries stream=sample_rate -of csv=p=0 "$f" | head -1)"

  # Decoded true peak, measured the same way the masterer measures it.
  tp="$("$FF" -hide_banner -nostats -i "$f" -af "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json" \
        -f null - 2>&1 | awk '/^{/{p=1} p{print} /^}/{p=0}' \
        | sed -n 's/.*"input_tp"[^"]*"\([^"]*\)".*/\1/p' | head -1)"

  reasons=""
  [[ "$arate" == "$WANT_SR" ]] || reasons+="rate!=$WANT_SR "
  [[ "$achan" == "$WANT_CH" ]] || reasons+="ch!=$WANT_CH "
  if [[ ! "$tp" =~ ^-?[0-9] ]]; then
    reasons+="peak-unmeasurable "
  elif awk -v tp="$tp" -v c="$CEIL_TP" 'BEGIN{exit !((tp+0) > (c+0))}'; then
    reasons+="peak>${CEIL_TP} "
  fi

  checked=$((checked + 1))
  if [[ -n "$reasons" ]]; then
    printf '%-30s %-8s %-4s %-9s %s\n' "$b" "${arate:--}" "$achan" "${tp:--}" "FAIL: $reasons"
    fail=$((fail + 1))
  else
    printf '%-30s %-8s %-4s %-9s %s\n' "$b" "$arate" "$achan" "$tp" "ok"
  fi
done

echo
if [[ $fail -gt 0 ]]; then
  echo "check-narration-audio: $fail/$checked audio-bearing clip(s) violate narration-audio.spec.json (v$(spec_get specVersion))." >&2
  echo "Re-master with: scripts/master-narration-audio.sh <clip> <clip>   (see docs/NARRATION_VOICE_STANDARD.md)" >&2
  exit 1
fi
echo "check-narration-audio: OK — $checked clip(s) mono ${WANT_SR}Hz, true peak <= ${CEIL_TP} dBTP${skipped:+ ($skipped silent skipped)}."
