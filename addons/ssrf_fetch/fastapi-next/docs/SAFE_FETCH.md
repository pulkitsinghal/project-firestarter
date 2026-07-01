# SSRF-guarded URL fetch (optional add-on)

A dependency-free helper for fetching a URL **server-side** without opening an
SSRF hole, for {{ project_name }}. Enabled at generation with
`include_ssrf_fetch=yes` (fastapi-next).

Server-side fetch shows up everywhere — link previews, webhooks, avatar-by-URL,
importing a document from a link — and each is an SSRF risk: a naïve fetch of a
user-supplied URL can be pointed at `http://169.254.169.254/` (cloud metadata),
`http://localhost:5432`, or an internal service. This add-on makes the safe path
the easy one.

## Usage

```python
from app.services.safe_fetch import fetch_url_text, UnsafeUrlError

try:
    text = await fetch_url_text(user_supplied_url)
except UnsafeUrlError:
    ...  # reject the request (e.g. HTTP 422)
```

`assert_safe_url(url)` is exposed too if you only need the validation (e.g. before
handing a URL to another fetcher).

## What it guards

- **Scheme:** `http`/`https` only (no `file://`, `ftp://`, `gopher://`, …).
- **Address:** the host must resolve **exclusively to public IPs** — every
  loopback / private / link-local / reserved / multicast / unspecified result is
  rejected (so `localhost`, `10.x`, `192.168.x`, `169.254.169.254`, `::1`,
  `0.0.0.0` are all blocked).
- **Redirects:** each hop is re-validated against the same rule, so a public URL
  can't 302 you onto an internal address (the classic bypass).
- **Bounds:** the response is size-capped (`MAX_BYTES`) and time-limited
  (`TIMEOUT_S`).
- HTML is reduced to text with the stdlib parser — **no new dependency**.

## Limits

Best-effort application-layer defense. A hardened deployment should **also**
egress through an allowlist proxy (defense in depth). DNS-rebinding between the
resolve-check and the connect is a known TOCTOU gap that a proxy closes.
