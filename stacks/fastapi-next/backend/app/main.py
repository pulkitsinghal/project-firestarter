"""{{ project_name }} — FastAPI entrypoint (skeleton).

This is intentionally minimal: a health check and one example endpoint that
reads from Postgres. Grow it by adding a domain layer (the place business logic
lives) and thin API adapters over it — never embed business logic in routes.
"""

from __future__ import annotations

import os

import psycopg
from fastapi import FastAPI

_DEFAULT_DB = "postgresql://postgres:postgres@postgres:5432/{{ db_name }}"
DATABASE_URL = os.environ.get("DATABASE_URL", _DEFAULT_DB)

app = FastAPI(title="{{ project_name }}")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "{{ project_slug }}-backend"}


@app.get("/api/items")
def list_items() -> dict[str, list[dict[str, object]]]:
    """Example read. Replace with your real domain endpoints."""
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name FROM items ORDER BY id;")
        rows = cur.fetchall()
    return {"items": [{"id": r[0], "name": r[1]} for r in rows]}
