"""User share ⟷ recovery code.

The user share is the root of a user's access. Everyday it lives in the device
keychain; to restore on a new device it is re-derived from a high-entropy
recovery code the user saved at setup (the single "keep this safe" moment).
Because the code is high-entropy, deriving the share from it is a plain KDF.

Recovery model (b): the system share plus the user's recovery code re-establish
access on a new device; neither the operator nor a lone system-share holder can.

Hardening after adversarial review: the code is stripped of ALL Unicode
whitespace and validated against its exact alphabet/length before use, so a
copy-paste artifact (trailing newline, non-breaking space) is reported as a
malformed code rather than silently deriving a wrong share and locking the user
out of their own data.
"""

from __future__ import annotations

import base64
import re
import secrets

from . import primitives as P

_RC_INFO = b"notebook/user-share-from-recovery/v1"
_RECOVERY_ENTROPY_BYTES = 20  # 160 bits → 32 base32 chars
_CODE_RE = re.compile(r"^[A-Z2-7]{32}$")  # RFC 4648 base32 alphabet, unpadded


class MalformedRecoveryCode(ValueError):
    """The recovery code is not a well-formed code (wrong alphabet/length). Raised
    distinctly so a formatting artifact is never confused with a valid-but-wrong
    code that would derive a usable-looking but incorrect share."""


def generate_recovery_code() -> str:
    """A high-entropy code, grouped for legibility like a wallet seed phrase."""
    raw = secrets.token_bytes(_RECOVERY_ENTROPY_BYTES)
    b32 = base64.b32encode(raw).decode("ascii").rstrip("=")
    return "-".join(b32[i : i + 5] for i in range(0, len(b32), 5))


def _normalize_code(code: str) -> bytes:
    if not isinstance(code, str):
        raise MalformedRecoveryCode("recovery code must be a string")
    # Strip ALL Unicode whitespace and grouping dashes, then uppercase.
    compact = re.sub(r"[\s-]+", "", code, flags=re.UNICODE).upper()
    if not _CODE_RE.match(compact):
        raise MalformedRecoveryCode("recovery code is malformed")
    return compact.encode("ascii")


def user_share_from_recovery_code(code: str, user_salt: bytes) -> bytes:
    """Deterministically derive the user share from a validated recovery code.
    `user_salt` is a per-user, non-secret value that only separates users so
    identical codes never collide. A wrong (but well-formed) code yields a wrong
    share, so every later decrypt fails closed."""
    return P.hkdf_sha256(ikm=_normalize_code(code), salt=user_salt, info=_RC_INFO)
