"""Auth endpoints: passwordless OTP login over email/phone, plus session checks.

Login *upgrades* the calling anonymous device (X-Device-Id) by linking it to an
account, so state follows the account. Auth is never required; these routes are
opt-in. The OAuth seam (identity linking) is in place in the store; the OAuth
HTTP flow is a documented follow-up (see docs/AUTH.md).
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from app.auth.store import AuthStore
from app.core.config import settings
from app.core.deps import get_auth_store, get_current_user
from app.models.auth import AuthResult, User
from app.services.auth import AuthError, RateLimited, logout, request_otp, verify_otp

router = APIRouter(prefix="/auth", tags=["auth"])

Store = Annotated[AuthStore, Depends(get_auth_store)]
CurrentUser = Annotated[User | None, Depends(get_current_user)]
OptDeviceId = Annotated[str | None, Header(alias="X-Device-Id")]


class OtpRequest(BaseModel):
    identifier: str
    channel: Literal["email", "phone"] = "email"


class OtpRequestResponse(BaseModel):
    sent: bool = True
    # Present only when AUTH_EXPOSE_DEBUG_OTP is set and delivery was console, so
    # local testing needs no mail/SMS. Never populated in production.
    debug_code: str | None = None


class OtpVerifyRequest(BaseModel):
    identifier: str
    channel: Literal["email", "phone"] = "email"
    code: str


@router.post("/otp/request", response_model=OtpRequestResponse)
async def otp_request(req: OtpRequest, store: Store, request: Request) -> OtpRequestResponse:
    # Always report "sent" regardless of whether an account exists (no enumeration).
    try:
        code = await request_otp(
            store,
            request.app.state.otp_deliverer,
            settings,
            identifier=req.identifier,
            channel=req.channel,
        )
    except RateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OtpRequestResponse(sent=True, debug_code=code)


@router.post("/otp/verify", response_model=AuthResult)
async def otp_verify(
    req: OtpVerifyRequest, store: Store, x_device_id: OptDeviceId = None
) -> AuthResult:
    """Verify the code; returns the session token (store it) and the account."""
    try:
        return await verify_otp(
            store,
            settings,
            identifier=req.identifier,
            channel=req.channel,
            code=req.code,
            device_id=x_device_id,
        )
    except RateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/me", response_model=User)
async def me(user: CurrentUser) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="not signed in")
    return user


@router.post("/logout", status_code=204)
async def logout_route(
    store: Store,
    authorization: Annotated[str | None, Header()] = None,
    x_session_token: Annotated[str | None, Header()] = None,
) -> None:
    token = x_session_token or (
        authorization[7:].strip()
        if authorization and authorization.lower().startswith("bearer ")
        else None
    )
    if token:
        await logout(store, token)
