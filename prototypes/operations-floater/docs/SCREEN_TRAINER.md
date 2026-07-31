# Screen Trainer (visual EHR-layout trainer)

The Screen Trainer replaces the terminal `watchful_train.py` geometry read-out
with an on-screen **overlay**: the local vision model's read is *drawn* on top of
the screen as labeled boxes, and the clinician corrects it visually and by typing.
Every correction feeds the same PHI-free, on-device learning loop.

This is **slice 1** — a bounded first cut for owner review. It ships the overlay,
pointer + typed correction, and the "what I'm learning" feed, and it *architects*
(does not build) the voice layer.

## PHI boundary (absolute)

Nothing in this feature is, or can become, PHI.

- **Development and tests use synthetic frames only** (`synthetic_ehr.py`). No real
  Citrix/EHR screen is ever captured, read, or loaded during development.
- At runtime on the clinician's machine, real capture (a separate, out-of-band
  step) sends a frame **only** to the local model at `http://localhost:11434`,
  then deletes it. No frame, pixel, or screen text ever leaves the device, and
  none ever enters this app's model or persistence.
- The overlay **draws over** the screen; it never captures pixels.
- Regions are **normalized rectangles** (`0…1`) plus a structure-only element tag
  — never pixels, never absolute screen coordinates, never screen text.
- The correction store holds only a content-free layout **signature** + a workflow
  **tag** (+ an optional local embedding, and the clinician's own typed note). The
  note is authored by him, kept on-device, and never embedded or transmitted.

## What slice 1 does

1. **Overlay** — `ScreenTrainerOverlayWindowController` hosts the overlay in a
   borderless, transparent, always-on-top `NSWindow` that can join all Spaces and
   be toggled **click-through** (`ignoresMouseEvents`) so work continues in the
   EHR beneath it. `ScreenTrainerRegionsLayer` draws each candidate region as a
   labeled box (element tag + confidence), dashed until corrected, with corner
   handles on the selected box.
2. **Correct it visually** — click a box to select it; **Confirm** (reinforce),
   **Relabel** (cycle the element tag), or **drag a corner** to adjust the box.
3. **Correct it by typing** — a free-text field captures the clinician's own note
   alongside the correction, into the **same** on-device store.
4. **"What I'm learning" panel** — a live feed that narrates each correction as it
   happens (any modality) and states what it now believes, e.g.
   *"This screen → results-review (full-width-grid) · reinforced 2×"*.
5. **The learning loop** — `ScreenTrainerMemory` is a faithful Swift port of
   `watchful_memory.py` (nearest-class-centroid over local embeddings, with
   leave-one-out recall), and `ScreenTrainerCorrectionStore` writes the same
   `{ts,label,signature,embedding,…}` JSONL the Python loop reads. Native overlay
   and Python read-out share one on-device memory.

## Data path

```
frame (synthetic in dev; real only at runtime, local-only, then deleted)
  → local vision model (qwen2.5vl @ localhost Ollama)         OllamaScreenReader
  → candidate regions + workflow + layout signature           ScreenReadout
  → overlay draws labeled boxes                               ScreenTrainerRegionsLayer
  → clinician corrects: pointer / drag / typed note           ScreenTrainerSession
  → one funnel: narrate + persist PHI-free exemplar           ScreenTrainerCorrectionStore
  → nearest-centroid memory improves                          ScreenTrainerMemory  (== watchful_memory.py)
```

`OllamaScreenReader` is **wired, not productionized**: the request/parse seams are
pure and tested, but the capture + network call runs only on the clinician's
machine at runtime. The synthetic model (`SyntheticScreenTrainerModel`) drives the
demo and every test, so the whole loop runs offline with no capture and no PHI.

## One loop, many inputs (voice is architected, not built)

Pointer, typed, and — next — voice all route through the single funnel
`ScreenTrainerSession.commit(...)`. The voice seam is explicit:
`ScreenTrainerSession.applyVoiceCorrection(workflow:transcript:)` and the
`ScreenTrainerVoiceIntake` protocol. The next slice adds mic → **on-device**
speech-to-text → `applyVoiceCorrection`, with the same "here's what I just learned"
narration. No audio, transcript, or frame ever leaves the device; listening stays
default-off and explicit, matching the app's existing voice posture.

## Try it

Open the overlay in the app: **Operations Floater ▸ Screen Trainer Overlay**
(seeded with a synthetic read-out). Toggle **Click-through** to keep working
beneath it.

Render the review still (offscreen, no window shown) over a synthetic frame:

```bash
python3 /path/to/verbal-orders/tools/synthetic_ehr.py \
  --one results-review --path /tmp/frame.png
swift run OperationsFloater \
  --render-trainer-demo /tmp/screen-trainer-demo.png \
  --trainer-demo-frame /tmp/frame.png \
  --trainer-demo-label results-review
```

## What's next (owner reviews slice 1 first)

- **Voice** — the architected layer above.
- **Live capture wiring** — connect the runtime capture step to `OllamaScreenReader`
  on-device (kept out of this slice to hold the PHI boundary during development).
- **Embedding backfill** — attach the local `nomic-embed-text` embedding on each
  correction so `ScreenTrainerMemory` recall runs natively, exactly as the Python
  loop does today.
- **Per-region workflow inference** and richer element vocabulary as the owner
  confirms the interaction feels right.
