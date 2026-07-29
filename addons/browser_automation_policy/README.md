# `browser_automation_policy` add-on

An opt-in, stack-agnostic, source-only policy and semantic-adapter contract for
future browser automation. It ships a Python-stdlib policy kernel, closed JSON
schemas, separate semantic DOM, Relative XY, Citrix/remote, and voice-intent
adapters, a content-minimized action ledger/evidence boundary, and hermetic
synthetic adversarial fixtures.

Capability grants bind the adapter, typed action/effect, target kind, and full
target-contract digest. Relative XY training bounds and generations are
proposal- and handoff-bound; they are never supplied as a separate evaluation
argument.

The add-on never installs or drives a browser. It contains no executor, browser
extension, host permission, profile/session access, input injection,
screenshot/OCR path, credential handling, network client, or deployment step.
Its only successful terminal output is a short-lived, grant-bounded,
nonce/idempotency-bound handoff that a separately approved future executor
could consume through a shared durable ledger.

Enable it while stamping:

```bash
./bin/firestart.sh --defaults --set include_browser_automation_policy=yes
```

The generated project receives `tools/browser_automation_policy/`. Run its
hermetic validation before integrating any observer or executor:

```bash
PYTHONPATH=. python3 -B -m tools.browser_automation_policy.run_validation
```
