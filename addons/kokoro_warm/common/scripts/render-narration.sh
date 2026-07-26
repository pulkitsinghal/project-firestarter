#!/usr/bin/env bash
# Generate Warm Heart narration audio locally from a text script.
#
# Voice + loudness defaults come from narration-audio.spec.json (the same file
# the masterer and guard read), so the voice identity lives in one place too.
# Override per-run with NARRATION_VOICE / NARRATION_MODEL / NARRATION_SPEED only
# for a documented exception (see docs/NARRATION_VOICE_STANDARD.md).
#
# Output is a mono, spec-sample-rate WAV, lightly leveled; the authoritative
# 2-pass loudness pass happens later in scripts/master-narration-audio.sh when
# the narration is muxed into the finished clip.
#
# Requirements: Apple Silicon, `mlx_audio.tts.generate` (the Kokoro TTS), and
# FFmpeg. This is the one step that needs the local model; see docs/KOKORO_WARM.md
# for running it as a small tailnet service so other machines can request speech.
#
# Usage: render-narration.sh INPUT_TEXT OUTPUT_WAV
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 INPUT_TEXT OUTPUT_WAV" >&2
  exit 64
fi
input_text=$1
output_wav=$2

if [[ ! -f "$input_text" ]]; then
  echo "Narration source not found: $input_text" >&2
  exit 66
fi

for command_name in mlx_audio.tts.generate ffmpeg; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command not found: $command_name" >&2
    exit 69
  fi
done

# shellcheck source=scripts/narration-spec.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/narration-spec.sh"
voice="${NARRATION_VOICE:-$(spec_get voiceId)}"
model="${NARRATION_MODEL:-$(spec_get voiceModel)}"
speed="${NARRATION_SPEED:-$(spec_get voiceSpeed)}"
sr="$(spec_get sampleRate)"
i_lufs="$(spec_get integratedLufs)"
ceil_tp="$(spec_get truePeakCeilingDbtp)"
spec_require_vars "voiceId=$voice" "voiceModel=$model" "voiceSpeed=$speed" \
  "sampleRate=$sr" "integratedLufs=$i_lufs" "truePeakCeilingDbtp=$ceil_tp"

output_dir=$(dirname "$output_wav")
output_name=$(basename "$output_wav" .wav)
raw_dir=$(mktemp -d)
trap 'rm -rf "$raw_dir"' EXIT
mkdir -p "$output_dir"

mlx_audio.tts.generate \
  --model "$model" \
  --text "$(<"$input_text")" \
  --voice "$voice" \
  --speed "$speed" \
  --output_path "$raw_dir" \
  --file_prefix narration \
  --audio_format wav \
  --join_audio

ffmpeg -y -v error \
  -i "$raw_dir/narration.wav" \
  -af "loudnorm=I=${i_lufs}:TP=${ceil_tp}:LRA=7" \
  -ar "$sr" -ac 1 \
  "$output_dir/$output_name.wav"

echo "Rendered $output_dir/$output_name.wav with $voice"
