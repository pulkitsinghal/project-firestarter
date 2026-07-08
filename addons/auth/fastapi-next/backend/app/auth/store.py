"""Auth persistence seam.

A `Protocol` plus an in-memory implementation (the live default and the test
backend). State resets on process restart — fine for the MVP/demo; a durable
Postgres store + migration is the documented follow-up (see docs/AUTH.md). No
business logic lives here; the auth *flows* (code generation, hashing, expiry)
live in `services/auth.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.models.auth import AuthSession, OtpChallenge, User


class AuthStore(Protocol):
    async def get_user(self, user_id: str) -> User | None: ...
    async def create_user(
        self,
        *,
        email: str | None = None,
        phone: str | None = None,
        display_name: str | None = None,
    ) -> User: ...
    async def find_user_by_identity(self, provider: str, subject: str) -> User | None: ...
    async def link_identity(self, provider: str, subject: str, user_id: str) -> None: ...
    async def put_challenge(self, challenge: OtpChallenge) -> None: ...
    async def get_challenge(self, identifier: str) -> OtpChallenge | None: ...
    async def clear_challenge(self, identifier: str) -> None: ...
    async def create_session(self, session: AuthSession) -> None: ...
    async def get_session(self, token_hash: str) -> AuthSession | None: ...
    async def delete_session(self, token_hash: str) -> None: ...
    async def link_device(self, device_id: str, user_id: str) -> None: ...
    async def user_for_device(self, device_id: str) -> str | None: ...
    async def devices_for_user(self, user_id: str) -> list[str]: ...
    # Rolling per-bucket counter (e.g. "req:<id>", "fail:<id>") for rate limiting
    # and a brute-force budget that survives re-requesting a fresh code.
    async def hit(self, bucket: str, window_sec: int) -> int: ...
    async def count(self, bucket: str, window_sec: int) -> int: ...
    async def reset(self, bucket: str) -> None: ...


class InMemoryAuthStore:
    """Dependency-free auth store. The live default; resets on restart."""

    def __init__(self) -> None:
        self._users: dict[str, User] = {}
        self._identities: dict[tuple[str, str], str] = {}  # (provider, subject) -> user_id
        self._challenges: dict[str, OtpChallenge] = {}  # identifier -> challenge
        self._sessions: dict[str, AuthSession] = {}  # token_hash -> session
        self._device_links: dict[str, str] = {}  # device_id -> user_id
        self._counters: dict[str, list[datetime]] = {}  # bucket -> hit timestamps

    async def get_user(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    async def create_user(
        self,
        *,
        email: str | None = None,
        phone: str | None = None,
        display_name: str | None = None,
    ) -> User:
        user = User(id=str(uuid.uuid4()), email=email, phone=phone, display_name=display_name)
        self._users[user.id] = user
        return user

    async def find_user_by_identity(self, provider: str, subject: str) -> User | None:
        user_id = self._identities.get((provider, subject))
        return self._users.get(user_id) if user_id else None

    async def link_identity(self, provider: str, subject: str, user_id: str) -> None:
        self._identities[(provider, subject)] = user_id

    async def put_challenge(self, challenge: OtpChallenge) -> None:
        self._challenges[challenge.identifier] = challenge

    async def get_challenge(self, identifier: str) -> OtpChallenge | None:
        return self._challenges.get(identifier)

    async def clear_challenge(self, identifier: str) -> None:
        self._challenges.pop(identifier, None)

    async def create_session(self, session: AuthSession) -> None:
        self._sessions[session.token_hash] = session

    async def get_session(self, token_hash: str) -> AuthSession | None:
        return self._sessions.get(token_hash)

    async def delete_session(self, token_hash: str) -> None:
        self._sessions.pop(token_hash, None)

    async def link_device(self, device_id: str, user_id: str) -> None:
        self._device_links[device_id] = user_id

    async def user_for_device(self, device_id: str) -> str | None:
        return self._device_links.get(device_id)

    async def devices_for_user(self, user_id: str) -> list[str]:
        return [d for d, uid in self._device_links.items() if uid == user_id]

    def _live(self, bucket: str, window_sec: int) -> list[datetime]:
        cutoff = datetime.now(UTC) - timedelta(seconds=window_sec)
        kept = [t for t in self._counters.get(bucket, []) if t >= cutoff]
        self._counters[bucket] = kept
        return kept

    async def hit(self, bucket: str, window_sec: int) -> int:
        kept = self._live(bucket, window_sec)
        kept.append(datetime.now(UTC))
        return len(kept)

    async def count(self, bucket: str, window_sec: int) -> int:
        return len(self._live(bucket, window_sec))

    async def reset(self, bucket: str) -> None:
        self._counters.pop(bucket, None)
