"""Smoke tests for the OTP auth flow — in-memory, no DB, no network.

Drives the async flow functions via `asyncio.run` so no pytest-asyncio plugin
(or extra dependency) is needed.
"""

from __future__ import annotations

import asyncio

import pytest

from app.auth.store import InMemoryAuthStore
from app.core.config import Settings
from app.services.auth import AuthError, request_otp, resolve_session, verify_otp


class _EchoDeliverer:
    """Console-like: not delivered out-of-band, so the code may be echoed."""

    async def deliver(self, *, identifier: str, channel: str, code: str) -> bool:
        return False


def _settings() -> Settings:
    return Settings(auth_secret="test-secret", expose_debug_otp=True)


def test_otp_request_verify_and_session_roundtrip() -> None:
    async def scenario() -> None:
        store = InMemoryAuthStore()
        settings = _settings()

        code = await request_otp(
            store, _EchoDeliverer(), settings, identifier="A@Example.com ", channel="email"
        )
        assert code is not None and len(code) == 6

        result = await verify_otp(
            store, settings, identifier="a@example.com", channel="email", code=code, device_id="d1"
        )
        # Identifier is normalized, so the two spellings are one account.
        assert result.user.email == "a@example.com"
        assert result.token

        user = await resolve_session(store, result.token)
        assert user is not None and user.id == result.user.id

    asyncio.run(scenario())


def test_wrong_code_is_rejected() -> None:
    async def scenario() -> None:
        store = InMemoryAuthStore()
        settings = _settings()
        await request_otp(
            store, _EchoDeliverer(), settings, identifier="a@example.com", channel="email"
        )
        with pytest.raises(AuthError):
            await verify_otp(
                store,
                settings,
                identifier="a@example.com",
                channel="email",
                code="000000",
                device_id=None,
            )

    asyncio.run(scenario())
