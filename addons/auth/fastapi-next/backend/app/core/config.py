"""Auth configuration (env-driven, dependency-free).

Every value reads from the environment with a safe default. The one secret —
`AUTH_SECRET` (the HMAC key for OTP codes) — must be set in any shared/production
deployment; if unset it falls back to a per-process random with a warning, so
local dev works but codes/sessions won't survive a restart or span workers.
Never bake a real secret into an image (see SECURITY.md).
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass

logger = logging.getLogger("{{ project_slug }}.auth")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _auth_secret() -> str:
    val = os.environ.get("AUTH_SECRET", "").strip()
    if val:
        return val
    logger.warning(
        "AUTH_SECRET is unset — using a per-process ephemeral key. OTP codes and "
        "sessions will not survive a restart or span multiple workers. Set "
        "AUTH_SECRET in any shared deployment."
    )
    return secrets.token_hex(32)


@dataclass(frozen=True)
class Settings:
    auth_secret: str
    otp_ttl_min: int = 10  # a code is valid this long
    otp_window_min: int = 15  # rolling window for the rate-limit / brute-force budgets
    otp_max_requests: int = 5  # code requests per identifier per window
    otp_max_attempts: int = 5  # wrong guesses per identifier per window
    session_ttl_days: int = 30
    expose_debug_otp: bool = False  # echo the code in the API response — DEV ONLY
    # Optional SMTP (email OTP via the operator's own mailbox; stdlib smtplib).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_sender: str = ""


def load_settings() -> Settings:
    return Settings(
        auth_secret=_auth_secret(),
        otp_ttl_min=_int("AUTH_OTP_TTL_MIN", 10),
        otp_window_min=_int("AUTH_OTP_WINDOW_MIN", 15),
        otp_max_requests=_int("AUTH_OTP_MAX_REQUESTS", 5),
        otp_max_attempts=_int("AUTH_OTP_MAX_ATTEMPTS", 5),
        session_ttl_days=_int("AUTH_SESSION_TTL_DAYS", 30),
        expose_debug_otp=_bool("AUTH_EXPOSE_DEBUG_OTP"),
        smtp_host=os.environ.get("SMTP_HOST", ""),
        smtp_port=_int("SMTP_PORT", 587),
        smtp_username=os.environ.get("SMTP_USERNAME", ""),
        smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        smtp_sender=os.environ.get("SMTP_SENDER", ""),
    )


settings = load_settings()
