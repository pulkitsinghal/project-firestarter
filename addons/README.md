# Add-ons

Optional modules kept out of the default scaffold and overlaid only when a project
opts in. The generator overlays `addons/<name>/common/` (stack-agnostic), then
`addons/<name>/<stack>/` when the matching `include_<name>` flag is `yes`.

```bash
./bin/firestart.sh --set include_<name>=yes
```

## The index is in ANATOMY, not here

**[`docs/ANATOMY.md` → Optional add-ons](../docs/ANATOMY.md#optional-add-ons-addons)** is the
one registry: every add-on, its flag, what it ships and what it buys you. This file is a signpost
and deliberately does **not** repeat that list, because a second list is a second thing to drift.

`bin/check-addon-registry.sh` fails the build if a directory here has no row there, which is how
three add-ons were found undocumented in August 2026.

## If you are looking for something specific

You almost certainly want to `grep docs/ANATOMY.md` rather than `ls` this directory. A directory
name tells you nothing about whether the thing solves your problem. Two that get re-invented most
often, because their names do not say what they do:

- **`kokoro_warm`** is the narration standard. One voice (Kokoro `af_heart`), one delivery chain
  (mono, 48 kHz, -16 LUFS, -1.5 dBTP), a guard that fails out-of-spec clips, a local text-to-WAV
  renderer, and a sync script whose `--check` mode fails on drift. If you are about to write
  anything that speaks, read `addons/kokoro_warm/common/docs/KOKORO_WARM.md` first.
- **`convergent_deploy`** is how several agents publish to one static site without waiting for
  each other or deleting each other's work.

## Adopting an add-on into a project that was not stamped with it

Copy the component and then keep it synced. `kokoro_warm` ships the pattern:
`sync-kokoro-warm.sh` re-pulls from firestarter, writes `.upstream-sha`, and `--check` fails when
the copy has drifted. A copy with no `.upstream-sha` is an unmanaged fork and will silently rot.
