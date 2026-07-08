"""Fetch a URL server-side, safely — an SSRF-guarded, dependency-free helper.

Server-side URL fetching (link previews, webhooks, avatar-by-URL, importing a
document) is a top SSRF risk. This guards it: http/https only; the host must
resolve exclusively to PUBLIC IPs (no loopback/private/link-local/reserved/
multicast/unspecified); redirects are re-validated against the same rule; and the
response is size- and time-bounded. HTML is reduced to text with the stdlib
parser — no new dependency.

Best-effort defense; a hardened deployment should also egress through an
allowlist proxy. Usage:  text = await fetch_url_text("https://example.com/x")
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlparse

MAX_BYTES = 2_000_000
TIMEOUT_S = 10
_UA = "{{ project_slug }}/0.1 (safe-fetch)"


class UnsafeUrlError(ValueError):
    """The URL is not allowed (bad scheme, or resolves to a non-public address)."""


def _is_blocked_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def assert_safe_url(url: str) -> None:
    """Raise UnsafeUrlError unless `url` is http/https and resolves only to public IPs."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeUrlError(f"unsupported URL: {url!r}")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"could not resolve host: {parsed.hostname}") from exc
    for info in infos:
        if _is_blocked_ip(str(info[4][0])):
            raise UnsafeUrlError(f"host resolves to a non-public address: {parsed.hostname}")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        assert_safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self.parts.append(text)


def html_to_text(html: str) -> str:
    """Reduce HTML to readable text (script/style/noscript stripped)."""
    parser = _TextExtractor()
    parser.feed(html)
    return " ".join(parser.parts)


def _fetch(url: str) -> str:
    assert_safe_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    opener = urllib.request.build_opener(_SafeRedirect())
    with opener.open(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 (scheme validated above)
        content_type = str(resp.headers.get("content-type", ""))
        raw: bytes = resp.read(MAX_BYTES)
    text: str = raw.decode("utf-8", errors="replace")
    if "html" in content_type.lower() or text.lstrip().startswith("<"):
        text = html_to_text(text)
    return text.strip()


async def fetch_url_text(url: str) -> str:
    """Fetch and return the readable text at `url`. Raises UnsafeUrlError if blocked."""
    return await asyncio.to_thread(_fetch, url)
