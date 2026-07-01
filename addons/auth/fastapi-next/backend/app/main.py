"""{{ project_name }} — FastAPI entrypoint (auth add-on enabled).

Adds passwordless OTP sign-in on top of the skeleton. Auth is optional — the
health/example endpoints work without signing in. Sessions live in an in-memory
store by default (reset on restart); wiring a durable store is a documented
follow-up (see docs/AUTH.md).
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI

from app.api.auth_routes import router as auth_router
from app.auth.delivery import build_deliverer
from app.auth.store import InMemoryAuthStore
from app.core.config import settings

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/{{ db_name }}"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auth wiring: an in-memory store + an OTP deliverer (console, or SMTP when
    # SMTP_HOST is set). Swap in a durable store here — see docs/AUTH.md.
    app.state.auth_store = InMemoryAuthStore()
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
