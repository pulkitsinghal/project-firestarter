# Third-party inputs — your LICENSE does not cover what you did not write

Your repository ships a LICENSE for the code you wrote. It says nothing about
the code, data, and assets you did not write but still redistribute. This file
is where you record those, because the two are not the same document and the
second one is the one that gets you in trouble.

<!-- third-party-inputs:start -->

## The rule

Your outbound LICENSE covers the first-party code you wrote, never the
third-party inputs you consume or the artifacts you derive from them. Every
project consumes inputs it did not author — vendored blobs, fonts, icon sets,
sample or seed data, model weights, scraped fixtures, container base images —
and each arrives under its own terms. The rule is process, not domain:
enumerate what you redistribute, record the terms it arrives under, and never
declare an outbound license broader than the narrowest input it covers.

The dependency runs one way: you cannot know your license until you audit your
inputs. A permissive outbound license is a claim about every byte you ship, so
it is only ever as true as the narrowest term among the inputs standing behind
it.

## The input inventory

Record one row per input you redistribute or derive from, and keep it beside the
code so the terms are auditable rather than aspirational:

| Input | Source | Terms | Redistributable? | Where it lives | What we publish |
|---|---|---|---|---|---|
| _e.g._ a web font | the foundry's site | SIL OFL 1.1 | yes, with its notice | `assets/fonts/` | the font file and its OFL notice |
| _e.g._ a sample dataset | a public portal | the portal's data-use terms | no | gitignored `data/raw/` | nothing; only the loader that fetches it |
| _e.g._ pretrained weights | the model card | the model's own license | per field | `models/` | only the fields the license permits |

## Two mechanics worth generalizing

**Withhold the artifact, ship the builder.** When a single input is not
redistributable, the restricted artifact is not published; the script that
regenerates it from the licensed source is. Nothing reproducible is lost and
nothing unlicensed is redistributed, so one restricted column never forces you
to withhold the whole derived work.

**A known-incomplete audit is recorded as incomplete, never as clear.** Tracing
one variable through prose is not auditing the schema: a terms audit that
checked some inputs is recorded as incomplete, never as clear, and the inputs it
did not reach are named so the next pass is a diff rather than a fresh act of
trust. This is the status-label family applied to licensing — an unexamined term
is not a permissive one.

## Fail closed

An input whose terms you have not verified is non-redistributable until audited.
Transport is not a grant: fetching a file, vendoring it, or locking its bytes
with a digest proves you hold the bytes, never that you may ship them. When the
release-parity vendor manifest pins a blob, it records a terms field beside the
digest for exactly this reason — the digest proves the bytes did not drift, and
the terms field is where you state whether they may leave.

<!-- third-party-inputs:end -->

## See also

- [`../LICENSE`](../LICENSE) — the outbound declaration this audit backs.
- [`COMPLIANCE_POSTURE.md`](COMPLIANCE_POSTURE.md) — the regulatory-scope axis; redistribution rights are the separate axis recorded here.
- [`DEFERRED_WORK.md`](DEFERRED_WORK.md) — where an unfinished input audit is parked as a leaf record instead of silently dropped.
