# Screen Trainer (visual EHR-layout trainer)

The Screen Trainer replaces the terminal `watchful_train.py` geometry read-out
with an on-screen **overlay**: the local vision model's read is *drawn* on top of
the screen as labeled boxes, and the clinician corrects it visually and by typing.
Every correction feeds the same PHI-free, on-device learning loop.

**Slice 1** shipped the overlay, pointer + typed correction, and the "what I'm
learning" feed against a **synthetic** read, and *architected* (did not build) the
voice layer.

**Slice 2 (this change) makes the read REAL.** A **Capture / Read screen** button
enumerates the owner's on-screen windows with ScreenCaptureKit, auto-suggests the
**Citrix Viewer** window, captures one downscaled frame of the picked window, and
feeds it to the **LOCAL** qwen2.5vl model over localhost Ollama. The model's
candidate regions become the overlay's real read; the owner then confirms /
relabels / drags / types exactly as in slice 1, into the same on-device store.
The synthetic model still drives the demo and every test — no real screen is ever
captured or read in development or CI.

### Real capture (slice 2)

- `ScreenCaptureService` (`ScreenCapture.swift`) wraps ScreenCaptureKit:
  `listWindows()` (`SCShareableContent`) → `[CaptureCandidateWindow]` (a Sendable
  value type; the `SCWindow` never escapes), and `captureBase64(windowID:)`
  (`SCScreenshotManager`) → a downscaled base64 JPEG. `CitrixWindowHeuristic`
  auto-suggests the Citrix Viewer window; `FrameDownscale` caps the longest edge;
  `FrameEncoder` serializes the frame.
- `OllamaScreenReader.read(base64Frame:…)` POSTs the frame to
  `http://localhost:11434` and parses the reply into a `ScreenReadout`.
- `ScreenCaptureController` is the button's state machine (list → auto-capture /
  choose → capture → read → deliver). Its seams are injected, so the whole flow is
  unit-tested with a synthetic frame and no screen access.
- `ScreenTrainerSession.applyLiveReadout(_:)` swaps the synthetic default for the
  real read and narrates it — **without** persisting a correction (a read is the
  model's guess; the owner's confirm/relabel is what teaches the store).
- **Screen Recording** needs **no** Hardened Runtime entitlement — it is TCC-gated
  like Input Monitoring, and the grant binds to the app's stable **signed** code
  identity, so a Developer ID build grants it once and it persists. An advisory
  `NSScreenCaptureUsageDescription` documents intent (macOS shows a generic
  prompt).

### Owner steps to run the real read

1. **Grant Screen Recording to the installed, Developer-ID-signed
   `/Applications/Operations Floater.app`** ahead of time: System Settings ▸
   Privacy & Security ▸ Screen Recording ▸ enable Operations Floater. Because the
   grant binds to the signed identity, do this on the *signed* app (not a
   disposable ad-hoc build, whose grant will not carry over).
2. Build + sign + notarize this branch with the owner's Developer ID via
   `scripts/sign-and-notarize.sh` and install it over `/Applications` (same
   identity ⇒ the Screen Recording grant carries over; relaunch if prompted).
3. Open the overlay: **Operations Floater ▸ Screen Trainer Overlay** (`⌘T`).
4. Click **Capture / Read screen**. It auto-suggests the **Citrix Viewer** window
   (or shows a chooser); pick it. The overlay draws the model's **real** read.
5. Confirm / relabel / drag the boxes, or type a note. The **"what I'm learning"**
   panel updates and the correction is stored on-device.

Verify the capture→encode→local-model→readout wiring with a **synthetic** frame
(no window capture, no PHI):

```bash
swift run OperationsFloater --capture-selftest            # hits the local model
swift run OperationsFloater --capture-selftest --capture-selftest-no-model  # encode only
```

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

As of slice 2 the capture + localhost inference is **wired and callable**
(`ScreenCaptureService` + `OllamaScreenReader.read`), but it runs ONLY on the
owner's machine when he clicks **Capture / Read screen** and points it at a
window. The synthetic model (`SyntheticScreenTrainerModel`) still drives the demo
and every automated test, and `--capture-selftest` exercises the real
encode→model→parse path with a synthetic frame, so development and CI run offline
with no real capture and no PHI.

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

## Author-your-own overlay LAYER system (Photoshop-style)

Beyond correcting the model's read, the clinician **authors his own overlays** and
stacks them on top, managed Photoshop-style. This is the foundation for the
semantic knowledge-graph of the EHR UI that the later agentic layer plans over.

- **Data model** (`ScreenTrainerLayers.swift`). An `OverlayLayer` is one authored
  component: `{id, normalizedRect, label, purpose, actionLaneIndex, groupID,
  visible}` — WHERE it sits, WHAT it is (`label`), WHY it exists (`purpose`, free
  text), WHEN it happens (`actionLaneIndex`, its slot in the workflow
  click-sequence), which clinical context it belongs to (`groupID`), and its own
  show/hide. `OverlayGroup`s (e.g. `inpatient` / `outpatient`) collect layers with
  per-group show/hide. `OverlayComposition` is the pure document holding the whole
  stack, with all Photoshop semantics as pure functions:
  - `isEffectivelyVisible` = the layer's own flag **AND** its group's flag.
  - `renderableLayers` returns EXACTLY what draws (hidden layers and layers in
    hidden groups are excluded) — the render guarantee lives in the model, not the
    view.
  - `actionLaneSequence` orders every layer by its workflow slot — the sequence the
    agentic layer will plan over.
  - `addLayer` / `addGroup` / `toggleLayer` / `toggleGroup` / `moveLayer` /
    `moveGroup` / `assignLayer` / `updateLayer` / `removeLayer` / `removeGroup`.
- **Layers panel** (`ScreenTrainerLayersPanel.swift`). Lists groups and their
  layers, each with a show/hide eye and reorder controls, plus an **add overlay**
  affordance: label + purpose + action-lane slot + group. `AuthoredOverlaysLayer`
  reuses the `NormalizedRect` box-drawing plumbing and draws only
  `renderableLayers` — hidden layers never draw.
- **Persistence** (`OverlayCompositionStore`). A single PHI-free JSON document
  beside the correction store under Application Support, git-ignored, holding only
  author-supplied labels, purposes, normalized positions, workflow-order indices,
  group names, and visibility. No frame, pixels, or screen text — never PHI, the
  same posture as the typed correction note.

## What's next

- **Context toggle** — surface groups as first-class clinical-context switches in
  the overlay (show only the active context's layers).
- **Mermaid graph** — export the authored layers + action lanes as the EHR-UI
  knowledge graph.
- **Agentic composition** — plan click-sequences over `actionLaneSequence` to
  accomplish untaught goals, behind a hard propose-confirm safety gate.
- **Voice** — the architected correction layer above.
- **Embedding backfill** — attach the local `nomic-embed-text` embedding on each
  correction so `ScreenTrainerMemory` recall runs natively, exactly as the Python
  loop does today.
