"""FastAPI dependencies for the auth layer."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request

from app.auth.store import AuthStore
from app.models.auth import User
from app.services.auth import resolve_session


def get_auth_store(request: Request) -> AuthStore:
    return request.app.state.auth_store


def _bearer(authorization: str | None, x_session_token: str | None) -> str | None:
    if x_session_token:
        return x_session_token
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


async def get_current_user(
    store: Annotated[AuthStore, Depends(get_auth_store)],
    authorization: Annotated[str | None, Header()] = None,
    x_session_token: Annotated[str | None, Header()] = None,
) -> User | None:
    """Resolve the signed-in account from a bearer/session token, or None."""
    token = _bearer(authorization, x_session_token)
    if not token:
        return None
    return await resolve_session(store, token)
