"""Known-answer vectors — pinned inputs → exact outputs.

These are the cross-client vectors the CryptoKit and WebCrypto ports MUST also
reproduce byte-for-byte; if any client's primitives differ, its output diverges
from these literals and the parity is caught. They also lock the deterministic
functions against silent drift (a canonicalization or KDF change turns these red).

Vectors are published so a port can verify itself before it is trusted. Sealing
uses a fresh random nonce per call, so the full seal has no single fixed output —
but AES-256-GCM IS a known-answer function under a pinned nonce, and the AAD wire
format and record layout are fully deterministic, so both are pinned below. A
port that reproduces every deterministic vector AND the pinned-nonce AEAD output
matches this reference byte-for-byte.
"""

from __future__ import annotations

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import notebook_crypto as nc
from notebook_crypto.envelope import _FIELD_LAYER, _WRAP_LAYER, RecordContext

U = bytes.fromhex("00" * 32)
S = bytes.fromhex("11" * 32)
SALT = bytes.fromhex("22" * 16)
CODE = "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE-FFFFF-GG"
CTX = RecordContext(b"tenantA", b"name", b"row1", b"1")


def test_kek_vector():
    assert nc.derive_kek(U, S).hex() == "a2792a3f4511b37c65c658d0269bb0e7510f54849eedd7c511ed28f6fef4c2d4"


def test_blind_index_key_vector():
    assert nc.derive_bi_key(U, S).hex() == "7b774086c1294af3c472ba3c6271e64e664e3dc0601b950a7fc4e167d537a6e3"


def test_blind_index_vector():
    bik = nc.derive_bi_key(U, S)
    assert nc.blind_index(bik, "Metoprolol") == "029f06282a8f1977150a0be02b8b2cd1c3c04d1081c98295f59c5020f2dee815"


def test_user_share_from_recovery_code_vector():
    assert (
        nc.user_share_from_recovery_code(CODE, SALT).hex()
        == "3e1668f15744696d2cc1c769d32a1c41e6d20a400997371cb708e783d4cbe0c1"
    )


def test_canonicalize_vector():
    # fullwidth + zero-width joiner + case + surrounding whitespace all fold away
    assert nc.canonicalize("  Ｍｅ‍TOPROLOL  ") == "metoprolol"


def test_aad_wire_format_vector():
    # The exact AAD bytes for both layers — a port MUST reproduce these or its
    # ciphertexts are incompatible / its context binding differs.
    assert CTX.aad(_WRAP_LAYER).hex() == (
        "000000146e6f7465626f6f6b2f64656b2d777261702f7631"
        "0000000774656e616e7441000000046e616d6500000004726f77310000000131"
    )
    assert CTX.aad(_FIELD_LAYER).hex() == (
        "000000116e6f7465626f6f6b2f6669656c642f7631"
        "0000000774656e616e7441000000046e616d6500000004726f77310000000131"
    )


def test_aead_pinned_nonce_vector():
    # AES-256-GCM is a known-answer function under a pinned nonce. This pins the
    # field-layer wire format end to end (a port's GCM + AAD must match).
    key = bytes.fromhex("00" * 32)
    nonce = bytes.fromhex("00" * 12)
    ct = AESGCM(key).encrypt(nonce, b"metoprolol", CTX.aad(_FIELD_LAYER))
    assert ct.hex() == "a3c234523d12040268226b55492495592b0b7aa458c61cb3d051"
