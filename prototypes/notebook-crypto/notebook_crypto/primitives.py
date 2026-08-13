"""Thin wrappers over vetted primitives (pyca/cryptography → OpenSSL).

Nothing here is invented crypto. Every function is a standard primitive that
Apple CryptoKit and the browser WebCrypto API also implement, so the same inputs
produce the same bytes on every client — which the cross-client test vectors then
prove. Keep this file small and boring: the moment it stops being an obvious
wrapper, it needs the same scrutiny as a primitive, which is exactly what we are
avoiding.
"""

from __future__ import annotations

import hmac as _stdlib_hmac
import os

from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

NONCE_LEN = 12  # AES-GCM standard nonce
KEY_LEN = 32    # AES-256


def random_bytes(n: int) -> bytes:
    return os.urandom(n)


def aead_encrypt(key: bytes, plaintext: bytes, aad: bytes = b"") -> tuple[bytes, bytes]:
    """AES-256-GCM. Returns (nonce, ciphertext||tag). Fresh random nonce each call."""
    if len(key) != KEY_LEN:
        raise ValueError("key must be 32 bytes")
    nonce = os.urandom(NONCE_LEN)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    return nonce, ciphertext


def aead_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes = b"") -> bytes:
    """AES-256-GCM open. Raises cryptography.exceptions.InvalidTag on a wrong key,
    wrong AAD, or any tampering — it never returns garbage."""
    if len(key) != KEY_LEN:
        raise ValueError("key must be 32 bytes")
    return AESGCM(key).decrypt(nonce, ciphertext, aad)


def hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int = KEY_LEN) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def hmac_sha256(key: bytes, msg: bytes) -> bytes:
    h = hmac.HMAC(key, hashes.SHA256())
    h.update(msg)
    return h.finalize()


def ct_equal(a: bytes, b: bytes) -> bool:
    """Constant-time comparison."""
    return _stdlib_hmac.compare_digest(a, b)
