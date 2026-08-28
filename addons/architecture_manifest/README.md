# `architecture_manifest` add-on

An opt-in, disabled-by-default, stack-agnostic, source-only add-on that turns a
closed **architecture manifest** into deterministic, reviewable artifacts: a
Mermaid graph and an ANATOMY-style Markdown table. A drift check binds those
rendered artifacts back to the manifest so a stale diagram is caught in CI
instead of during an incident.

The manifest describes the *shape* of a system, not its contents: components,
data stores, dependencies, trust boundaries, owner roles, and repo-relative
evidence links. Every entity is a product-owned opaque token, a finite enum, or
a repo-relative path. Real hostnames, URLs, IP addresses, connection strings,
credentials, absolute paths, and free prose are not fields in the contract.

The vocabulary is derived independently from Firestarter/Auggie needs and
neutral public standards: the W3C PROV entity/agent/relation model (derivation
is a partial order, so `depends-on` / `derives-from` edges must stay acyclic),
JSON Schema 2020-12 for the closed contracts, and general Mermaid conventions
for the render layer. No gallery submission was consulted.

The add-on uses the Python standard library only. It runs no network, no
subprocess, no AST crawler, and no model. It emits no absolute paths and holds
no identity. Rendering and drift detection are pure, deterministic functions.

Enable it while stamping:

```bash
./bin/firestart.sh --defaults --set include_architecture_manifest=yes
```

The generated project receives `tools/architecture_manifest/`. Run its hermetic
validation before wiring it into any pipeline:

```bash
PYTHONPATH=. python3 -B -m tools.architecture_manifest.run_validation
```

See `common/tools/architecture_manifest/docs/ARCHITECTURE_MANIFEST.md` for the
concept and drift workflow, and `docs/INTEGRATION_AND_ROLLBACK.md` for adoption
and removal.
