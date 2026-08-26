# `reviewed_extraction` add-on

An opt-in, stack-agnostic, source-only contract for human-reviewed structured
extraction. It ships a Python-stdlib claim contract, a deterministic egress
reducer, an allowlisted egress builder, an evidence verifier that keeps raw
source content caller-side, closed JSON schemas, and hermetic synthetic
adversarial fixtures.

Each claim declares an opaque field path, a bounded value token, a closed review
state (`proposed`, `confirmed`, `corrected`, `unknown`, `omitted`, `conflicted`,
`superseded`), an opaque decision actor, purpose-limitation metadata (purpose +
recipient), and evidence referenced by source ID, `sha256:` digest, and integer
offsets. The extracted value a reviewer confirmed is carried; the raw source
span it came from is never inlined.

The reducer folds a claim set into one decision per field path with documented
supersession, conflict, and correction precedence. The egress builder releases
only fields that were explicitly confirmed or corrected AND requested AND
purpose/recipient-matched; everything else is dropped fail-closed. The model
never authors the payload, and the add-on never reads a document, runs a model,
or sends anything.

Enable it while stamping:

```bash
./bin/firestart.sh --defaults --set include_reviewed_extraction=yes
```

The generated project receives `tools/reviewed_extraction/`. Run its hermetic
validation before integrating any extractor or reviewer surface:

```bash
PYTHONPATH=. python3 -B -m tools.reviewed_extraction.run_validation
```
