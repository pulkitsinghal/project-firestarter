"""{{ project_name }} — FastAPI entrypoint (auth add-on enabled).

Adds passwordless OTP sign-in on top of the skeleton. Auth is optional — the
health/example endpoints work without signing in. The store is in-memory by
default (resets on restart); set AUTH_STORE=postgres for the durable Postgres
store (apply migration 002_auth.sql first). See docs/AUTH.md.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI

from app.api.auth_routes import router as auth_router
from app.auth.delivery import build_deliverer
from app.auth.store import AuthStore, InMemoryAuthStore
from app.core.config import settings

_DEFAULT_DB = "postgresql://postgres:postgres@postgres:5432/{{ db_name }}"
DATABASE_URL = os.environ.get("DATABASE_URL", _DEFAULT_DB)


def _build_auth_store() -> AuthStore:
    """In-memory by default; Postgres (durable) when AUTH_STORE=postgres."""
    if os.environ.get("AUTH_STORE", "memory").strip().lower() == "postgres":
        from app.auth.postgres_store import PostgresAuthStore

        return PostgresAuthStore(DATABASE_URL)
    return InMemoryAuthStore()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Auth wiring: the chosen store + an OTP deliverer (console, or SMTP when
    # SMTP_HOST is set).
    app.state.auth_store = _build_auth_store()
    app.state.otp_deliverer = build_deliverer(settings)
    yield


app = FastAPI(title="{{ project_name }}", lifespan=lifespan)
app.include_router(auth_router)


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
