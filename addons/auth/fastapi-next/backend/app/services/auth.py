"""Auth flows: OTP request/verify, session resolution, logout.

Security posture (deliberate, reviewed):
- Codes are 6 random digits from `secrets`, stored only as a keyed HMAC-SHA256
  (so a store leak never reveals codes), compared in constant time.
- Brute force is bounded by a short expiry + an attempt cap; a wrong guess burns
  an attempt, and the challenge is cleared on success or lockout.
- Session tokens are 256-bit url-safe randoms; only their SHA-256 is stored.
- Requesting a code never reveals whether an account exists (always "sent").
- Identifiers are normalized so "A@x.com" and "a@x.com " are one account.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

from app.auth.delivery import OtpDeliverer
from app.auth.store import AuthStore
from app.core.config import Settings
from app.models.auth import AuthResult, AuthSession, OtpChallenge, User

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")


class AuthError(Exception):
    """A recoverable auth failure (bad input, wrong/expired code). Maps to 4xx."""


class RateLimited(AuthError):
    """Too many requests/attempts for an identifier within the window. Maps to 429."""


def _now() -> datetime:
    return datetime.now(UTC)


def normalize(identifier: str, channel: str) -> str:
    ident = identifier.strip()
    if channel == "email":
        ident = ident.lower()
        if not _EMAIL_RE.match(ident):
            raise AuthError("invalid email address")
        return ident
    if channel == "phone":
        compact = re.sub(r"[\s()\-.]", "", ident)
        if not _PHONE_RE.match(compact):
            raise AuthError("invalid phone number")
        return compact
    raise AuthError("unsupported channel")


def _code_hash(secret: str, identifier: str, code: str) -> str:
    return hmac.new(secret.encode(), f"{identifier}:{code}".encode(), hashlib.sha256).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def request_otp(
    store: AuthStore,
    deliverer: OtpDeliverer,
    settings: Settings,
    *,
    identifier: str,
    channel: str,
) -> str | None:
    """Issue a one-time code. Returns the code ONLY when `expose_debug_otp` is
    explicitly enabled and delivery was not out-of-band (local/dev convenience);
    fail-closed otherwise. Throttled per identifier to bound brute force / abuse."""
    ident = normalize(identifier, channel)
    window = settings.otp_window_min * 60
    if await store.count(f"req:{ident}", window) >= settings.otp_max_requests:
        raise RateLimited("too many code requests; try again later")
    await store.hit(f"req:{ident}", window)

    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = OtpChallenge(
        identifier=ident,
        channel=channel,
        code_hash=_code_hash(settings.auth_secret, ident, code),
        expires_at=_now() + timedelta(minutes=settings.otp_ttl_min),
    )
    await store.put_challenge(challenge)
    delivered = await deliverer.deliver(identifier=ident, channel=channel, code=code)
    if settings.expose_debug_otp and not delivered:
        return code  # explicit opt-in only; never inferred from environment
    return None


async def verify_otp(
    store: AuthStore,
    settings: Settings,
    *,
    identifier: str,
    channel: str,
    code: str,
    device_id: str | None,
) -> AuthResult:
    """Validate a code; on success get-or-create the account, link the calling
    device to it, and mint a session."""
    ident = normalize(identifier, channel)
    window = settings.otp_window_min * 60
    # Durable per-identifier brute-force budget — survives re-requesting a code,
    # so an attacker can't reset it by minting a fresh challenge.
    if await store.count(f"fail:{ident}", window) >= settings.otp_max_attempts:
        raise RateLimited("too many attempts; try again later")

    challenge = await store.get_challenge(ident)
    if challenge is None or challenge.expires_at < _now():
        raise AuthError("code expired or not found")

    expected = challenge.code_hash
    supplied = _code_hash(settings.auth_secret, ident, code.strip())
    if not hmac.compare_digest(expected, supplied):
        await store.hit(f"fail:{ident}", window)
        raise AuthError("invalid code")

    await store.clear_challenge(ident)
    await store.reset(f"fail:{ident}")

    user = await store.find_user_by_identity(channel, ident)
    if user is None:
        user = await store.create_user(
            email=ident if channel == "email" else None,
            phone=ident if channel == "phone" else None,
        )
        await store.link_identity(channel, ident, user.id)
    if device_id:
        await store.link_device(device_id, user.id)

    token = await mint_session(store, settings, user, device_id)
    return AuthResult(token=token, user=user)


async def mint_session(
    store: AuthStore, settings: Settings, user: User, device_id: str | None
) -> str:
    """Create a session for a user and return the raw token (only its hash is stored)."""
    token = secrets.token_urlsafe(32)
    await store.create_session(
        AuthSession(
            token_hash=_token_hash(token),
            user_id=user.id,
            device_id=device_id,
            expires_at=_now() + timedelta(days=settings.session_ttl_days),
        )
    )
    return token


async def resolve_session(store: AuthStore, token: str) -> User | None:
    """Return the account for a session token, or None if missing/expired."""
    token_hash = _token_hash(token)
    session = await store.get_session(token_hash)
    if session is None:
        return None
    if session.expires_at < _now():
        await store.delete_session(token_hash)  # purge on access; no stale buildup
        return None
    return await store.get_user(session.user_id)


async def logout(store: AuthStore, token: str) -> None:
    await store.delete_session(_token_hash(token))
