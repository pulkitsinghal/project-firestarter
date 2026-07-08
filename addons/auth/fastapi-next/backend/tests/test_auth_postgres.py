"""Integration test for PostgresAuthStore.

Skips unless a Postgres reachable at DATABASE_URL has migration 002_auth.sql
applied (so it runs green in CI once the stack is up + migrated, and is skipped
in hermetic/unit environments). Drives the real OTP flow through the durable
store so a restart-surviving sign-in is actually exercised.
"""

from __future__ import annotations

import asyncio
import os

import pytest

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/{{ db_name }}"
)


def _pg_ready() -> bool:
    try:
        import psycopg

        with psycopg.connect(DATABASE_URL, connect_timeout=2) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.auth_otp')")
            row = cur.fetchone()
            return bool(row and row[0] is not None)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_ready(), reason="Postgres with auth tables (002_auth.sql) not available"
)


class _EchoDeliverer:
    async def deliver(self, *, identifier: str, channel: str, code: str) -> bool:
        return False


def test_postgres_store_otp_roundtrip() -> None:
    async def scenario() -> None:
        from app.auth.postgres_store import PostgresAuthStore
        from app.core.config import Settings
        from app.services.auth import request_otp, resolve_session, verify_otp

        store = PostgresAuthStore(DATABASE_URL)
        settings = Settings(auth_secret="test-secret", expose_debug_otp=True)
        # Unique per process so repeated runs don't collide on the contact.
        ident = f"pg-test-{os.getpid()}@example.com"

        code = await request_otp(
            store, _EchoDeliverer(), settings, identifier=ident, channel="email"
        )
        assert code is not None

        result = await verify_otp(
            store, settings, identifier=ident, channel="email", code=code, device_id="dev-1"
        )
        assert result.user.email == ident

        # Durable: a fresh store instance (new connection) resolves the session.
        user = await resolve_session(PostgresAuthStore(DATABASE_URL), result.token)
        assert user is not None and user.id == result.user.id

    asyncio.run(scenario())
