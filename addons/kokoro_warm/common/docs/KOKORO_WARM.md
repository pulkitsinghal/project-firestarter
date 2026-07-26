# kokoro_warm add-on — narration audio, one standard

A stack-agnostic way to give every narrated video in {{ project_name }} the same
voice and the same delivery audio — and to **keep it that way**. It distills a
sibling project's fix for help-clip audio that had drifted out of spec (mixed
48 k/96 k sample rates, plosive-popping true peaks) because nothing enforced the
standard and clips were finished ad hoc.

Enable it at stamp time:

```bash
./bin/firestart.sh --set include_kokoro_warm=yes
```

## What you get

| File | Purpose |
|------|---------|
| `scripts/narration-audio.spec.json` | **Single source of truth** for the audio + voice numbers (mono · 48 kHz · -16 LUFS · -1.5 dBTP ceiling · -2.5 encode target · HP 80 + limiter · AAC 96k · `af_heart`/Kokoro-82M). Bump `specVersion` on any change. |
| `scripts/narration-spec.sh` | Tiny dependency-free reader (no jq/python/node) so the scripts below all read the one spec and cannot drift apart. |
| `scripts/master-narration-audio.sh` | The delivery audio chain: high-pass + limiter → 48 kHz mono → 2-pass loudnorm; copies video + captions **bit-for-bit**, re-encodes only audio. Run it as the final stage of any clip render, or by hand on a Descript export. |
| `scripts/check-narration-audio.sh` | The guard: ffprobes your clips and fails if any audio-bearing clip is not mono 48 kHz or exceeds -1.5 dBTP. |
| `scripts/render-narration.sh` | Local Warm Heart (Kokoro `af_heart`) text→WAV generator. Voice defaults come from the spec. |
| `scripts/sync-kokoro-warm.sh` | Re-pull the component from firestarter (`--check` fails on drift) so you stay on the shared standard instead of forking it. |
| `.github/workflows/narration-audio.yml` | Runs the guard on every PR (host runner + ffmpeg). Non-blocking by default — see *Make it a gate* below. |
| `.github/workflows/narration-audio-sync.yml` | Weekly drift check: opens one tracking issue if this copy no longer matches firestarter. |
| `docs/NARRATION_VOICE_STANDARD.md` | The prose standard (delivery, voice, exceptions). |

## Setup

1. Point the guard at your narrated clips. Either pass a path, or set the repo
   variable the workflow reads:
   ```bash
   gh variable set NARRATION_VIDEO_DIR --body "public/videos"
   ```
   A missing/empty directory is a **pass** (nothing to enforce yet), so a fresh
   stamp is never red.
2. Generate narration locally (Apple Silicon + `mlx_audio` + FFmpeg):
   ```bash
   scripts/render-narration.sh narration.txt build/narration.wav
   ```
3. Have your clip-render step finish through the master, e.g.:
   ```bash
   scripts/master-narration-audio.sh build/clip.premaster.mp4 public/videos/clip.mp4
   ```
4. Check locally any time:
   ```bash
   scripts/check-narration-audio.sh public/videos
   ```

## Make it a gate

The workflow runs on every PR but is **not** a required check by default (the
generated project's branch protection gates on `Tests` / `Lint & Typecheck` /
`Conventional Commits`). To make audio drift actually block a merge, add
**Narration Audio** to the required status checks in branch protection, or fold
`check-narration-audio.sh` into your stack's `precommit` target.

## Staying in sync

This component is **vendored** — a copy of firestarter's canonical version. So it
does not silently fork:

- `scripts/sync-kokoro-warm.sh` re-pulls the latest from firestarter and records
  the source commit in `.upstream-sha`.
- `scripts/sync-kokoro-warm.sh --check` fails if this copy has drifted (a local
  hand-edit, or firestarter moving on). The **Narration Audio Sync** workflow runs
  it weekly and opens one tracking issue on drift.

Do not hand-edit the component files. Evolve the standard in firestarter, then
re-sync here. (If you vendored the files into a subdirectory, point the scripts at
it with `KOKORO_WARM_DIR`.)

## Run it as a private service (optional)

The one step that needs the local Kokoro model is synthesis. If you want other
machines (or a teammate) to request Warm Heart speech without installing
Apple-Silicon + `mlx` locally, wrap the scripts behind a tiny HTTP endpoint on
the box that has the model, and reach it privately over your own tailnet. AI
callers on the same machine can just run the scripts directly — this is only for
reaching it from elsewhere.

Sketch — a dependency-free stdlib wrapper is enough:

```
POST /synthesize  { text }         -> audio/wav     (render-narration.sh)
POST /master      (multipart mp4)  -> audio/mp4     (master-narration-audio.sh)
POST /verify      (multipart mp4)  -> { compliant } (check-narration-audio.sh)
GET  /spec                         -> the JSON spec verbatim
```

Then expose it to *your own devices only* with Tailscale `serve` (a private
WireGuard mesh — nothing is public):

```bash
# on the box running the wrapper on 127.0.0.1:<port>
tailscale serve --bg --https=443 http://127.0.0.1:<port>
# -> https://<node>.<tailnet>.ts.net/  (reachable only from your tailnet)
```

Keep it on the private tailnet, never a public funnel/tunnel — there is no auth
in the sketch above. See project-firestarter `docs/REMOTE-ACCESS.md` for the full
Tailscale recipe (desktop app vs headless userspace, the macOS DNS caveat).

## Why one place

The audio numbers and the voice identity live in exactly one file
(`narration-audio.spec.json`); the master and the guard both read it, so the
target you encode to and the check that gates can never disagree. Tighten a rule
once (e.g. drop the ceiling to -2.0 dBTP), bump `specVersion`, and every clip and
every project that vendors this add-on inherits it.
