"""Account + session models for the optional auth layer.

Auth is an *upgrade* over an anonymous identity: a device links to a `User`
account so state follows the account across devices. The base experience stays
anonymous — auth is never required. No PII beyond the contact the user
volunteers (email or phone) or an OAuth identity.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class User(BaseModel):
    """An account. Identified by a volunteered email or phone (or an OAuth identity)."""

    model_config = {"frozen": True}

    id: str
    email: str | None = None
    phone: str | None = None
    display_name: str | None = None


class OtpChallenge(BaseModel):
    """A pending one-time code. Only the keyed hash is stored, never the code.

    The brute-force budget is tracked per *identifier* in the store's rolling
    counter (so it can't be reset by re-requesting a code), not on the challenge.
    """

    model_config = {"frozen": True}

    identifier: str  # normalized email or phone
    channel: str  # "email" | "phone"
    code_hash: str
    expires_at: datetime


class AuthSession(BaseModel):
    """A bearer session. Only the token's hash is persisted (the raw token is the secret)."""

    model_config = {"frozen": True}

    token_hash: str
    user_id: str
    device_id: str | None
    expires_at: datetime


class AuthResult(BaseModel):
    """Returned to the client on a successful login — the raw token plus the account."""

    model_config = {"frozen": True}

    token: str
    user: User
