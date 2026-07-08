"""Tests for the SSRF-guarded fetch helper — fully offline (no network)."""

from __future__ import annotations

import pytest

from app.services.safe_fetch import (
    UnsafeUrlError,
    _SafeRedirect,
    assert_safe_url,
    html_to_text,
)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",  # bad scheme
        "file:///etc/passwd",  # bad scheme
        "http:///nohost",  # no hostname
        "http://127.0.0.1/",  # loopback
        "http://localhost/",  # resolves to loopback
        "http://10.0.0.1/",  # private
        "http://192.168.1.1/",  # private
        "http://169.254.169.254/",  # link-local — the cloud metadata endpoint
        "http://[::1]/",  # ipv6 loopback
        "http://0.0.0.0/",  # unspecified
    ],
)
def test_blocks_unsafe_urls(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        assert_safe_url(url)


def test_html_to_text_strips_scripts_and_styles() -> None:
    html = "<html><body><p>Hello</p><script>evil()</script><style>x{}</style> world</body></html>"
    assert html_to_text(html) == "Hello world"


def test_redirect_to_internal_is_reblocked() -> None:
    # A 302 that points at an internal address must be rejected on the redirect,
    # not just the initial URL (the classic SSRF bypass).
    handler = _SafeRedirect()
    with pytest.raises(UnsafeUrlError):
        handler.redirect_request(None, None, 302, "Found", {}, "http://169.254.169.254/")


def test_bounds_are_set() -> None:
    from app.services.safe_fetch import MAX_BYTES, TIMEOUT_S

    assert MAX_BYTES > 0
    assert TIMEOUT_S > 0
