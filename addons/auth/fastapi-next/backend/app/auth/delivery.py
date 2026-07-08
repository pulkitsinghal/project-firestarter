"""One-time-code delivery boundary.

Delivery is pluggable so the auth core never hard-wires an external service. The
default needs **zero external infrastructure**: it logs the code server-side
(and, with `AUTH_EXPOSE_DEBUG_OTP=true`, the API echoes it so local testing needs
no mail/SMS setup).

- `ConsoleDeliverer` — default; no dependency, no subscription.
- `SmtpDeliverer`   — optional; sends email via the operator's own mailbox over
  stdlib `smtplib` (no third-party package, no subscription). Email only.

SMS has no free transport, so there is deliberately no bundled SMS provider:
phone codes fall back to the console deliverer (logged).
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

logger = logging.getLogger("{{ project_slug }}.auth")


class OtpDeliverer(Protocol):
    async def deliver(self, *, identifier: str, channel: str, code: str) -> bool:
        """Send the code. Return True if delivered out-of-band (so the API must
        NOT echo it), False if not (dev/console — safe to echo in non-prod)."""
        ...


class ConsoleDeliverer:
    """Reports the code as *not* delivered out-of-band.

    The code is logged only at DEBUG so it never lands in default (INFO+) logs;
    in local dev the API echoes it (see `AUTH_EXPOSE_DEBUG_OTP`).
    """

    async def deliver(self, *, identifier: str, channel: str, code: str) -> bool:
        logger.info("OTP issued (%s) for %s", channel, identifier)
        logger.debug("OTP (%s) for %s: %s", channel, identifier, code)
        return False


class SmtpDeliverer:
    """Sends email codes via the operator's own SMTP server (stdlib only)."""

    def __init__(self, *, host: str, port: int, username: str, password: str, sender: str) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender

    def _send(self, *, to: str, code: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = "Your {{ project_name }} sign-in code"
        msg["From"] = self._sender
        msg["To"] = to
        msg.set_content(f"Your sign-in code is {code}. It expires shortly.")
        with smtplib.SMTP(self._host, self._port, timeout=10) as server:
            # Verified TLS (cert + hostname) so credentials/codes aren't exposed
            # to a passive MITM on the SMTP hop.
            server.starttls(context=ssl.create_default_context())
            if self._username:
                server.login(self._username, self._password)
            server.send_message(msg)

    async def deliver(self, *, identifier: str, channel: str, code: str) -> bool:
        if channel != "email":
            # No SMS transport — let the caller fall back to console behavior.
            logger.info("OTP issued (%s) for %s", channel, identifier)
            logger.debug("OTP (%s) for %s: %s", channel, identifier, code)
            return False
        await asyncio.to_thread(self._send, to=identifier, code=code)
        return True


def build_deliverer(settings: object) -> OtpDeliverer:
    """Pick a deliverer from config: SMTP if a host is set, else console."""
    host = getattr(settings, "smtp_host", "")
    if host:
        return SmtpDeliverer(
            host=host,
            port=int(getattr(settings, "smtp_port", 587)),
            username=getattr(settings, "smtp_username", ""),
            password=getattr(settings, "smtp_password", ""),
            sender=getattr(settings, "smtp_sender", "") or getattr(settings, "smtp_username", ""),
        )
    return ConsoleDeliverer()
