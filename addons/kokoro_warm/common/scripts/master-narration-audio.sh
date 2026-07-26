#!/usr/bin/env bash
# Master one clip's narration audio to docs/NARRATION_VOICE_STANDARD.md.
#
# This is the single source of truth for the delivery audio CHAIN; the numbers
# it uses come from narration-audio.spec.json (shared with the guard). Have each
# clip-render script call it as its final stage, and/or run it by hand to
# re-master an already-exported clip (e.g. a Descript export). Given an MP4 it
#   1. high-passes and limits (kills plosive pops),
#   2. resamples to the spec sample rate, mono,
#   3. 2-pass loudnorm to the spec integrated loudness with a true-peak target
#      (encodeTruePeakDbtp) that leaves the lossy AAC encode headroom, so the
#      decoded output lands under the delivery ceiling (truePeakCeilingDbtp),
#   4. re-encodes ONLY the audio to AAC and copies the video + subtitle streams
#      bit-for-bit, so the picture and captions are untouched.
#
# Usage: master-narration-audio.sh INPUT.mp4 OUTPUT.mp4
#
# A clip with no audio stream is copied through unchanged (a warning is logged).
# Silence is a legitimate state for a clip that is not meant to carry narration;
# the audio guard (scripts/check-narration-audio.sh), not this masterer, is what
# fails a clip that ships out-of-spec audio.
set -euo pipefail

FF="${FFMPEG:-ffmpeg}"
FP="${FFPROBE:-ffprobe}"

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 INPUT.mp4 OUTPUT.mp4" >&2
  exit 64
fi
IN="$1"
OUT="$2"

command -v "$FF" >/dev/null 2>&1 || { echo "ffmpeg is required" >&2; exit 69; }
command -v "$FP" >/dev/null 2>&1 || { echo "ffprobe is required" >&2; exit 69; }
test -s "$IN" || { echo "Input clip is missing or empty: $IN" >&2; exit 66; }

# --- Load the shared audio contract (same file the guard reads) -------------
# shellcheck source=scripts/narration-spec.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/narration-spec.sh"
SR="$(spec_get sampleRate)"
CH="$(spec_get channels)"
HP="$(spec_get highpassHz)"
LIM="$(spec_get limiterLimit)"
LIM_A="$(spec_get limiterAttackMs)"
LIM_R="$(spec_get limiterReleaseMs)"
I_LUFS="$(spec_get integratedLufs)"
LRA="$(spec_get loudnessRange)"
ENC_TP="$(spec_get encodeTruePeakDbtp)"
BR="$(spec_get aacBitrate)"
spec_require_vars "sampleRate=$SR" "channels=$CH" "highpassHz=$HP" \
  "limiterLimit=$LIM" "limiterAttackMs=$LIM_A" "limiterReleaseMs=$LIM_R" \
  "integratedLufs=$I_LUFS" "loudnessRange=$LRA" "encodeTruePeakDbtp=$ENC_TP" \
  "aacBitrate=$BR"

# Deterministic pre-filters, applied identically in both loudnorm passes so the
# pass-1 measurement matches what pass 2 normalizes. limiterLimit ~0.891 = -1 dBFS.
PRE="highpass=f=${HP},alimiter=level_in=1:level_out=1:limit=${LIM}:attack=${LIM_A}:release=${LIM_R},aresample=${SR}"

# No audio stream -> nothing to master. Copy the clip through untouched so a
# legitimately silent render is not corrupted, and say so out loud.
have_audio="$("$FP" -v error -select_streams a -show_entries stream=index -of csv=p=0 "$IN" | head -1)"
if [[ -z "$have_audio" ]]; then
  echo "!!! $(basename "$IN"): no audio stream — copying through unmastered" >&2
  if [[ "$IN" != "$OUT" ]]; then cp "$IN" "$OUT"; fi
  exit 0
fi

echo ">>> mastering $(basename "$IN")"

# --- Pass 1: measure loudnorm stats on the pre-filtered signal ---
json_field() { printf '%s\n' "$1" | sed -n "s/.*\"$2\"[^\"]*\"\\([^\"]*\\)\".*/\\1/p" | head -1; }
meas="$("$FF" -hide_banner -nostats -i "$IN" \
  -af "${PRE},loudnorm=I=${I_LUFS}:TP=${ENC_TP}:LRA=${LRA}:print_format=json" \
  -f null - 2>&1 | awk '/^{/{p=1} p{print} /^}/{p=0}')"
mi="$(json_field "$meas" input_i)"
mtp="$(json_field "$meas" input_tp)"
mlra="$(json_field "$meas" input_lra)"
mth="$(json_field "$meas" input_thresh)"
off="$(json_field "$meas" target_offset)"
if [[ -z "$mi" || -z "$mtp" || -z "$mlra" || -z "$mth" || -z "$off" ]]; then
  echo "loudnorm measurement failed for $IN" >&2
  exit 1
fi
echo "    measured I=$mi TP=$mtp LRA=$mlra thresh=$mth offset=$off"

# Preserve a default subtitle stream if the clip carries one.
hassub="$("$FP" -v error -select_streams s:0 -show_entries stream=index -of csv=p=0 "$IN" | head -1)"
dispo=()
if [[ -n "$hassub" ]]; then dispo=(-disposition:s:0 default); fi

# --- Pass 2: apply, copy video + subs, re-encode audio only ---
TMP="$OUT.master.tmp.mp4"
trap 'rm -f "$TMP"' EXIT
"$FF" -y -v error -i "$IN" \
  -map 0:v:0 -map 0:a:0 -map 0:s? -map_metadata 0 \
  -af "${PRE},loudnorm=I=${I_LUFS}:TP=${ENC_TP}:LRA=${LRA}:measured_I=${mi}:measured_TP=${mtp}:measured_LRA=${mlra}:measured_thresh=${mth}:offset=${off}:linear=true:print_format=summary" \
  -c:v copy -c:s copy \
  -c:a aac -b:a "${BR}" -ar "${SR}" -ac "${CH}" \
  -metadata:s:a:0 handler_name="Warm Heart narration" \
  "${dispo[@]}" \
  -movflags +faststart \
  "$TMP"
mv "$TMP" "$OUT"
trap - EXIT
echo "    mastered -> $OUT"
