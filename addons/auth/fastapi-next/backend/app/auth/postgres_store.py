"""Durable Postgres implementation of AuthStore (migration 002_auth.sql).

A faithful persistence port of InMemoryAuthStore's semantics using psycopg3's
native async API — no extra dependency and no connection pool (a short-lived
connection per call, which is fine for a scaffold; add a pool for scale).
Enabled by AUTH_STORE=postgres so sign-ins survive a restart or span workers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from app.models.auth import AuthSession, OtpChallenge, User


def _user(row: tuple[Any, ...]) -> User:
    return User(id=str(row[0]), email=row[1], phone=row[2], display_name=row[3])


class PostgresAuthStore:
    """AuthStore backed by Postgres. Same semantics as InMemoryAuthStore."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def _conn(self) -> psycopg.AsyncConnection[Any]:
        # autocommit so a caught UniqueViolation doesn't poison a transaction.
        return await psycopg.AsyncConnection.connect(self._dsn, autocommit=True)

    async def get_user(self, user_id: str) -> User | None:
        async with await self._conn() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT id, email, phone, display_name FROM users WHERE id = %s",
                (uuid.UUID(user_id),),
            )
            row = await cur.fetchone()
        return _user(row) if row else None

    async def create_user(
        self,
        *,
        email: str | None = None,
        phone: str | None = None,
        display_name: str | None = None,
    ) -> User:
        async with await self._conn() as conn, conn.cursor() as cur:
            try:
                await cur.execute(
                    "INSERT INTO users (email, phone, display_name) VALUES (%s, %s, %s)"
                    " RETURNING id, email, phone, display_name",
                    (email, phone, display_name),
                )
                row = await cur.fetchone()
            except psycopg.errors.UniqueViolation:
                # Contact already maps to an account — reuse it (link by contact).
                await cur.execute(
                    "SELECT id, email, phone, display_name FROM users"
                    " WHERE (%s::text IS NOT NULL AND email = %s)"
                    "    OR (%s::text IS NOT NULL AND phone = %s) LIMIT 1",
                    (email, email, phone, phone),
                )
                row = await cur.fetchone()
        assert row is not None
        return _user(row)

    async def find_user_by_identity(self, provider: str, subject: str) -> User | None:
        async with await self._conn() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT u.id, u.email, u.phone, u.display_name FROM users u"
                " JOIN auth_identities i ON i.user_id = u.id"
                " WHERE i.provider = %s AND i.subject = %s",
                (provider, subject),
            )
            row = await cur.fetchone()
        return _user(row) if row else None

    async def link_identity(self, provider: str, subject: str, user_id: str) -> None:
        async with await self._conn() as conn, conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO auth_identities (provider, subject, user_id) VALUES (%s, %s, %s)"
                " ON CONFLICT (provider, subject) DO UPDATE SET user_id = EXCLUDED.user_id",
                (provider, subject, uuid.UUID(user_id)),
            )

    async def put_challenge(self, challenge: OtpChallenge) -> None:
        async with await self._conn() as conn, conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO auth_otp (identifier, channel, code_hash, expires_at)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT (identifier) DO UPDATE SET"
                " channel = EXCLUDED.channel, code_hash = EXCLUDED.code_hash,"
                " expires_at = EXCLUDED.expires_at",
                (
                    challenge.identifier,
                    challenge.channel,
                    challenge.code_hash,
                    challenge.expires_at,
                ),
            )

    async def get_challenge(self, identifier: str) -> OtpChallenge | None:
        async with await self._conn() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT identifier, channel, code_hash, expires_at FROM auth_otp"
                " WHERE identifier = %s",
                (identifier,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return OtpChallenge(identifier=row[0], channel=row[1], code_hash=row[2], expires_at=row[3])

    async def clear_challenge(self, identifier: str) -> None:
        async with await self._conn() as conn, conn.cursor() as cur:
            await cur.execute("DELETE FROM auth_otp WHERE identifier = %s", (identifier,))

    async def create_session(self, session: AuthSession) -> None:
        async with await self._conn() as conn, conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO auth_sessions (token_hash, user_id, device_id, expires_at)"
                " VALUES (%s, %s, %s, %s)",
                (
                    session.token_hash,
                    uuid.UUID(session.user_id),
                    session.device_id,
                    session.expires_at,
                ),
            )

    async def get_session(self, token_hash: str) -> AuthSession | None:
        async with await self._conn() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT token_hash, user_id, device_id, expires_at FROM auth_sessions"
                " WHERE token_hash = %s",
                (token_hash,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return AuthSession(
            token_hash=row[0], user_id=str(row[1]), device_id=row[2], expires_at=row[3]
        )

    async def delete_session(self, token_hash: str) -> None:
        async with await self._conn() as conn, conn.cursor() as cur:
            await cur.execute("DELETE FROM auth_sessions WHERE token_hash = %s", (token_hash,))

    async def link_device(self, device_id: str, user_id: str) -> None:
        async with await self._conn() as conn, conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO device_links (device_id, user_id) VALUES (%s, %s)"
                " ON CONFLICT (device_id) DO UPDATE SET user_id = EXCLUDED.user_id",
                (device_id, uuid.UUID(user_id)),
            )

    async def user_for_device(self, device_id: str) -> str | None:
        async with await self._conn() as conn, conn.cursor() as cur:
            await cur.execute("SELECT user_id FROM device_links WHERE device_id = %s", (device_id,))
            row = await cur.fetchone()
        return str(row[0]) if row else None

    async def devices_for_user(self, user_id: str) -> list[str]:
        async with await self._conn() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT device_id FROM device_links WHERE user_id = %s", (uuid.UUID(user_id),)
            )
            rows = await cur.fetchall()
        return [str(r[0]) for r in rows]

    async def hit(self, bucket: str, window_sec: int) -> int:
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=window_sec)
        async with await self._conn() as conn, conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM auth_rate_hits WHERE bucket = %s AND hit_at < %s", (bucket, cutoff)
            )
            await cur.execute(
                "INSERT INTO auth_rate_hits (bucket, hit_at) VALUES (%s, %s)", (bucket, now)
            )
            await cur.execute(
                "SELECT count(*) FROM auth_rate_hits WHERE bucket = %s AND hit_at >= %s",
                (bucket, cutoff),
            )
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def count(self, bucket: str, window_sec: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=window_sec)
        async with await self._conn() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT count(*) FROM auth_rate_hits WHERE bucket = %s AND hit_at >= %s",
                (bucket, cutoff),
            )
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def reset(self, bucket: str) -> None:
        async with await self._conn() as conn, conn.cursor() as cur:
            await cur.execute("DELETE FROM auth_rate_hits WHERE bucket = %s", (bucket,))
