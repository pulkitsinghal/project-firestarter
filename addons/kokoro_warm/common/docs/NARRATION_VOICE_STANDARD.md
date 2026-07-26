# Product narration voice standard

This is the default for narrated demos, onboarding videos, release walkthroughs,
and developer training across {{ project_name }}.

## Default voice

- **Brand name:** Warm Heart
- **Engine:** Kokoro 82M
- **Voice identifier:** `af_heart`
- **Reference model:** `mlx-community/Kokoro-82M-bf16`
- **Default synthesis speed:** `1.0`
- **Permitted finishing adjustment:** `atempo=1.05` to `1.12` when needed to
  fit an existing edit. Rewrite the script instead of exceeding that range.
- **Delivery:** warm, calm, conversational, credible, and helpful; never
  promotional or hurried.
- **Master format:** mono 48 kHz, normalized to `-16 LUFS`, with a true-peak
  ceiling of `-1.5 dBTP`.

The exact numbers above are also machine-readable in
[`scripts/narration-audio.spec.json`](../scripts/narration-audio.spec.json) — the
single source both the masterer and the guard read.

## Rule for humans and agents

Use Warm Heart automatically unless a product owner explicitly approves a
different voice. A change for one video is an exception, not a new default.
Record the exception and reason beside the media source.

Keep narration text in a tracked UTF-8 text file and subtitles in a tracked SRT
or VTT file. Generate speech outside Descript, then import the finished WAV into
Descript when its editing workflow is useful. This keeps voice generation local
and reproducible while preserving inexpensive visual editing.

## Reproduction

The local generator is:

```sh
scripts/render-narration.sh narration.txt narration.wav
```

Requirements: Apple Silicon, `mlx_audio.tts.generate`, FFmpeg, and the Kokoro
model. Voice, model, and speed default to the spec; override `NARRATION_VOICE`,
`NARRATION_MODEL`, or `NARRATION_SPEED` only for a documented exception.

## Enforcement (audio master)

The delivery numbers live once, machine-readable, in
[`scripts/narration-audio.spec.json`](../scripts/narration-audio.spec.json)
(mono, 48 kHz, `-16 LUFS`, `-1.5 dBTP` ceiling). Two scripts read that one file
so the target and the check can never disagree:

- **Master** — run every rendered clip through
  [`scripts/master-narration-audio.sh`](../scripts/master-narration-audio.sh) as
  its final stage: high-pass + limiter, resample to 48 kHz mono, and a 2-pass
  loudnorm that aims at `-2.5 dBTP` so the lossy AAC re-encode still lands under
  the `-1.5 dBTP` ceiling. The picture and captions are copied bit-for-bit. Run
  it by hand on any off-pipeline export (e.g. Descript) to bring it into spec.
- **Guard** — [`scripts/check-narration-audio.sh`](../scripts/check-narration-audio.sh)
  (wired as a CI job) ffprobes your narrated clips and fails the build if an
  audio-bearing clip is not mono 48 kHz or exceeds `-1.5 dBTP`. This is what
  stops the drift that ships mixed sample rates and plosive-popping true peaks.

See [`KOKORO_WARM.md`](KOKORO_WARM.md) for setup, wiring, and running the
generator as a small private tailnet service.
