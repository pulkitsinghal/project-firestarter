"""Per-user deterministic blind index for server-side MERGE/dedup.

The server dedups entities by canonical name WITHOUT reading the name: the client
computes HMAC-SHA256(bi_key, canonical(name)) and the server matches on the tag.

Hardening after adversarial review:
  * The blind-index key now derives from BOTH shares (like the KEK), not the user
    share alone. Previously a single-share holder could recover the whole name
    column by offline dictionary attack; now a tag cannot be computed or attacked
    without both shares, and the server (system share only) still cannot compute
    one. The client holds both shares at seal time, so no new exposure.
  * Canonicalization is NFKC + casefold + Unicode format-character stripping, so
    compatibility/fullwidth/ligature/ß/zero-width/soft-hyphen spellings of the
    same name dedup instead of silently fragmenting. Pinned by known-answer
    vectors for cross-client parity.
"""

from __future__ import annotations

import unicodedata

from . import primitives as P
from .envelope import _lp, _require_share

_BI_INFO = b"notebook/blind-index-key/v1"
_BI_SALT = b"notebook/blind-index/salt/v1"


def derive_bi_key(user_share: bytes, system_share: bytes) -> bytes:
    """Blind-index key from BOTH shares. The server (system share only) cannot
    derive it; a lone user share cannot either."""
    _require_share(user_share, "user_share")
    _require_share(system_share, "system_share")
    return P.hkdf_sha256(ikm=_lp(user_share) + _lp(system_share), salt=_BI_SALT, info=_BI_INFO)


def _strip_format(text: str) -> str:
    # Drop Unicode default-ignorable / format (category Cf) characters:
    # zero-width joiners/spaces (200B–200D), BOM (FEFF), soft hyphen (00AD), etc.
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def canonicalize(text: str) -> str:
    """The canonical form the MERGE identity keys on. NFKC folds compatibility and
    width variants; casefold is stronger than lower() for non-ASCII; format chars
    are removed; whitespace is collapsed. Any drift here silently breaks dedup, so
    it is pinned by tests and known-answer vectors."""
    t = unicodedata.normalize("NFKC", text)
    t = _strip_format(t).casefold()
    return " ".join(t.split())


def blind_index(bi_key: bytes, text: str) -> str:
    """Opaque, deterministic tag for `text`. Hex so it drops straight into a text
    column and an equality index."""
    return P.hmac_sha256(bi_key, canonicalize(text).encode("utf-8")).hex()
