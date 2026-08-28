# Architecture manifest 0.1

This package is a source-only reference contract for describing a system's
architecture as closed, content-minimized data and rendering it into
deterministic, drift-checkable artifacts. It observes nothing and controls
nothing; it is a pure function library over a JSON manifest.

## Data flow

```text
trusted author writes a closed manifest (opaque tokens + enums + repo paths)
             |
             v
load_manifest  ->  fail-closed validation (ManifestErrorCode)
             |
             v
ArchitectureManifest (order-independent canonical projection + digest)
             |
     +-------+-------------------+
     v                           v
render_mermaid              render_anatomy
(flowchart TD)             (ANATOMY table)
     |                           |
     +-----------+---------------+
                 v
           check_drift  ->  current | stale | malformed
```

Manifest content is data. A malformed, cyclic, absolute-path, or
identity-shaped manifest is rejected with a closed reason code; it never
reaches the render layer and never produces a false `current` drift verdict.

## Model

- **Trust boundaries** carry a finite `tier` (`public` .. `isolated`).
- **Components** (`service`, `library`, `job`, `gateway`, `ui`, `cli`,
  `adapter`, `external-system`) and **data stores** (`relational`, `document`,
  `key-value`, `graph`, `object-store`, `cache`, `search-index`, `queue`,
  `secret-store`) each sit in one boundary, carry an owner role + owner token,
  and require at least one evidence link.
- **Dependencies** are typed relations (`calls`, `reads`, `writes`,
  `publishes`, `subscribes`, `depends-on`, `derives-from`). Runtime relations
  may form cycles; `depends-on` / `derives-from` (PROV derivation order) must
  be acyclic.
- **Evidence links** are repo-relative paths with an optional `sha256:` digest.
  Absolute paths, URLs, hosts, and identities are rejected.

## Drift

`check_drift(manifest, rendered_text, artifact_kind)` compares the provided
artifact against a freshly rendered one by *normalized content*: line endings
are unified, trailing whitespace per line is stripped, and trailing blank lines
are dropped before a SHA-256 digest is taken. Cosmetic whitespace/EOL churn is
tolerated; any semantic change is reported as `stale`.

## Validation

The package uses only the Python standard library and synthetic fixtures:

```bash
PYTHONPATH=. python3 -B -m tools.architecture_manifest.run_validation
```

See `docs/ARCHITECTURE_MANIFEST.md` for the concept and schema, and
`docs/INTEGRATION_AND_ROLLBACK.md` for adoption and removal.
