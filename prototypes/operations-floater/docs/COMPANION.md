# Operations companion ("Ember")

Ember is a small, charming on-screen companion that lives in the bottom-trailing
corner of the dashboard. It gives the operations floater a friendly, glanceable
"face" for the same canonical state the rest of the surface already shows, and
nothing more. It is a presentation-only feature: it reads the snapshot, never
writes it, and performs no control-plane action.

![Every companion mood](media/companion-ember-gallery.jpg)

## What it reacts to

The companion's mood is a deterministic function of the canonical
`DashboardSnapshot` (reusing the already-tested `guideCue` classification) plus
one short, time-boxed celebration transient. No mood is derived from any image,
camera, microphone, network, analytics, or personal source.

| Dashboard state (highest priority first)                              | Mood          | Behavior                                                        |
| --------------------------------------------------------------------- | ------------- | -------------------------------------------------------------- |
| Verified failure, verified attention signal, or pending owner decision | `concerned`   | Drooped ears, worried brow, frown                              |
| A queue item just entered the finished (`ready`) lane                 | `celebrating` | Happy squint, open grin, blush, sparkles, a little hop (6 s)   |
| One or more lanes `running`                                           | `focused`     | Ears perked up, wide alert eyes, faster tail                   |
| Work `ready`/`queued` with nothing running                            | `staged`      | Ears up, content smile                                         |
| Items `waiting` on a dependency                                       | `waiting`     | Ears drooped, flat mouth                                       |
| Records exist but the queue is calm                                   | `idle`        | Gentle breathing and blinking                                 |
| No records at all                                                     | `sleeping`    | Closed eyes and a soft "z z z"                                 |

Concern always wins over a celebration, and a celebration never starts while the
companion is concerned — you never see the pet cheering while something is on
fire. The celebration is triggered only when the finished-lane count strictly
increases relative to the previous snapshot, so pre-existing finished work on
launch does not celebrate.

The status bubble restates only canonical lane counts (for example, "On it — 2
lanes running." or "3 items staged and ready to go.").

## Personality and motion

- Idle breathing and a deterministic blink.
- Ears perk up with focus and droop with concern or fatigue; a small twitch
  keeps them alive.
- A tail that wags faster the busier the queue is.
- Celebration sparkles and a hop; concerned brows and a frown.

Motion is a pure function of `(time, mood)`. **Reduce Motion produces a fully
stable frame** (open eyes, no bob, no hop), matching the existing guide avatar.

## Non-intrusive by design

- It sits in the corner with padding and only occupies its own footprint, so the
  rest of the dashboard stays interactive.
- It is **dismissible**: hovering reveals a close control that collapses the
  companion to a small wake button; the choice persists across launches via
  `AppStorage` (`OperationsFloater.CompanionDismissedV1`).
- It draws with SwiftUI `Canvas`, so it needs no external art asset.

## Files

| File                                        | Responsibility                                                              |
| ------------------------------------------- | --------------------------------------------------------------------------- |
| `Sources/OperationsFloater/CompanionPresentation.swift` | Pure, UI-free state machine: mood mapping, celebration reducer, poses, motion sampler, and status chatter. |
| `Sources/OperationsFloater/CompanionView.swift`         | SwiftUI: the vector-drawn `Canvas` character, live corner overlay, speech bubble, dismiss/wake control, mood gallery, and headless PNG renderer. |
| `Tests/OperationsFloaterTests/CompanionPresentationTests.swift` | State-machine, pose, motion, and chatter tests.                    |

The controller is wired into `DashboardView` in `OperationsFloaterApp.swift`; it
ingests each new snapshot and the pending-decision flag, and the effective mood
is recomputed at render time so the celebration decays smoothly without an extra
timer.

## Preview and tests

```bash
# State-machine, pose, motion, and chatter tests.
swift test --filter CompanionPresentationTests

# Headless still-frame gallery of every mood (offscreen rasterization; no window
# is foregrounded).
swift run OperationsFloater --render-companion-preview /tmp/ember-gallery.png
```

An Xcode canvas `#Preview` for both the gallery and the live corner companion is
included at the bottom of `CompanionView.swift`.
