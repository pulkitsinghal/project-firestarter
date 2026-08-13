"""The dual-key envelope: user + system shares BOTH required to decrypt.

Content is sealed under a random per-record DEK; the DEK is wrapped under a KEK
derived from BOTH shares. Missing/wrong either share → wrong KEK → the DEK
unwrap fails (AES-GCM auth error) → unreadable.

Two integrity properties the AAD enforces, both bound into the DEK wrap AND the
field encrypt so a whole-record swap cannot bypass them:
  * substitution — a sealed blob only opens against its own (tenant, field, row)
  * rollback — ...and only at its own version.

Hardening after adversarial review:
  * Shares are validated to be exactly 32 bytes and fail closed — an empty or
    short share never silently collapses the 2-of-2 (was a fail-open break).
  * The AAD is a length-prefixed, injective encoding of the record identity,
    including a version, so ciphertexts cannot be swapped between rows or rolled
    back (was substitutable/rollbackable within a (tenant, field)).
  * from_bytes is fully bounds-checked and fails closed on malformed input.

The load-bearing key-combination invariant still lives at the call sites:
`derive_kek` must run only on the user's device, where both shares are present.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import primitives as P

_KEK_INFO = b"notebook/dek-kek/v1"
_KEK_SALT = b"notebook/dek-kek/salt/v1"
_WRAP_LAYER = b"notebook/dek-wrap/v1"
_FIELD_LAYER = b"notebook/field/v1"


def _require_share(value: bytes, name: str) -> None:
    if not isinstance(value, (bytes, bytearray)) or len(value) != P.KEY_LEN:
        raise ValueError(f"{name} must be exactly {P.KEY_LEN} bytes (got {len(value) if hasattr(value, '__len__') else type(value).__name__})")


def _lp(part: bytes) -> bytes:
    """Length-prefixed encoding — makes any concatenation of parts injective, so
    no two distinct tuples of parts can produce the same byte string."""
    return struct.pack(">I", len(part)) + bytes(part)


def derive_kek(user_share: bytes, system_share: bytes) -> bytes:
    """KEK = HKDF-SHA256 over BOTH validated shares. 2-of-2: neither alone derives
    it, and an empty/short share is rejected rather than silently degrading."""
    _require_share(user_share, "user_share")
    _require_share(system_share, "system_share")
    # length-prefixed so (user||system) is unambiguous even if lengths ever vary
    return P.hkdf_sha256(ikm=_lp(user_share) + _lp(system_share), salt=_KEK_SALT, info=_KEK_INFO)


@dataclass(frozen=True)
class RecordContext:
    """The identity a sealed record is bound to. `row_id` is a stable per-entity
    identifier (a row UUID, or the entity's blind index); `version` is a
    caller-supplied monotonic value so a superseded ciphertext cannot be replayed.
    All are authenticated (as AAD), none are encrypted — they are already known to
    the server and carry no plaintext content."""

    tenant: bytes
    field: bytes
    row_id: bytes
    version: bytes

    def aad(self, layer: bytes) -> bytes:
        return _lp(layer) + _lp(self.tenant) + _lp(self.field) + _lp(self.row_id) + _lp(self.version)


@dataclass(frozen=True)
class SealedRecord:
    """Everything the server stores for one encrypted field: ciphertext, nonces,
    and the twice-wrapped DEK. No plaintext, no key material."""

    wrapped_dek_nonce: bytes
    wrapped_dek: bytes
    field_nonce: bytes
    field_ct: bytes

    def to_bytes(self) -> bytes:
        return b"".join(_lp(p) for p in (self.wrapped_dek_nonce, self.wrapped_dek, self.field_nonce, self.field_ct))

    @classmethod
    def from_bytes(cls, blob: bytes) -> "SealedRecord":
        if not isinstance(blob, (bytes, bytearray)):
            raise ValueError("SealedRecord.from_bytes expects bytes")
        blob = bytes(blob)
        vals, off, n = [], 0, len(blob)
        for _ in range(4):
            if off + 4 > n:
                raise ValueError("malformed SealedRecord: truncated length prefix")
            (ln,) = struct.unpack(">I", blob[off : off + 4])
            off += 4
            # `off + ln > n` already bounds every slice to the actual input the
            # caller is holding, so no allocation-amplification window exists —
            # and there is no arbitrary size cap, so any field that seals also
            # round-trips (no silent write/read asymmetry).
            if off + ln > n:
                raise ValueError("malformed SealedRecord: part length out of range")
            vals.append(blob[off : off + ln])
            off += ln
        if off != n:
            raise ValueError("malformed SealedRecord: trailing bytes")
        return cls(*vals)


def seal(
    plaintext: bytes, user_share: bytes, system_share: bytes, ctx: RecordContext
) -> SealedRecord:
    """Encrypt `plaintext` bound to `ctx`. The record only ever opens against the
    same (tenant, field, row_id, version)."""
    kek = derive_kek(user_share, system_share)
    dek = P.random_bytes(P.KEY_LEN)
    wnonce, wdek = P.aead_encrypt(kek, dek, aad=ctx.aad(_WRAP_LAYER))
    fnonce, fct = P.aead_encrypt(dek, plaintext, aad=ctx.aad(_FIELD_LAYER))
    return SealedRecord(wnonce, wdek, fnonce, fct)


def open_record(
    rec: SealedRecord, user_share: bytes, system_share: bytes, ctx: RecordContext
) -> bytes:
    """Decrypt a SealedRecord. Raises InvalidTag if either share is wrong/missing,
    if the record was moved to a different row, rolled back to an old version, or
    tampered."""
    kek = derive_kek(user_share, system_share)
    dek = P.aead_decrypt(kek, rec.wrapped_dek_nonce, rec.wrapped_dek, aad=ctx.aad(_WRAP_LAYER))
    return P.aead_decrypt(dek, rec.field_nonce, rec.field_ct, aad=ctx.aad(_FIELD_LAYER))
