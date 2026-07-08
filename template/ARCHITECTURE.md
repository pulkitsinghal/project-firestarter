# {{ project_name }} — Architecture

> Scaffolded from **project-firestarter**. Replace the placeholders below as the
> system takes shape. Keep this file truthful — the AI PR reviewer and every new
> session read it first.

## One-line thesis

{{ project_tagline }}

## The canonical flow

Describe the one non-negotiable request/data flow that defines the system, e.g.:

```
User Action → … → Persisted State → … → Response
```

## Layers

| Layer | Directory | Responsibility |
|-------|-----------|----------------|
| Data  | `backend/migrations/` | Forward-only schema; source of truth |
| Domain| `backend/…`           | Business logic; the only place rules live |
| API   | `backend/…`           | Thin adapters over the domain layer |
| Client| `frontend/` / `app/` / `splash/` | UI; never re-implements domain rules |

### Layer rules
- Business logic lives in the domain layer, never in the client and never in
  free-text LLM prompts.
- The client talks to the API only; it never reaches into the database directly.
- Migrations are forward-only and idempotent.

## Data model

Describe the core tables/entities and their relationships (an ER sketch helps).

## Invariants

The rules that must always hold (these become the AI reviewer's BLOCKING
criteria — see `.github/workflows/ai-pr-review.yml`):

1. Forward-only, idempotent migrations. `migrations/NNN_name.sql`.
2. No host SDKs — every toolchain is a profiled Docker Compose service.
3. _(project-specific invariant)_
4. _(project-specific invariant)_

## RPC / endpoint catalog

List the canonical operations and which layer owns each.
