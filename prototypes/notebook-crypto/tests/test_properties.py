"""The property matrix. Prove every combination; assume nothing.

Covers the guarantees AND the classes the first adversarial review found
untested: empty/short shares, cross-row substitution + rollback, dual-share
blind index, NFKC canonicalization, and malformed-input handling.
"""

from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidTag

import notebook_crypto as nc

USER_A = nc.random_bytes(32)
SYS_A = nc.random_bytes(32)
USER_B = nc.random_bytes(32)
SYS_B = nc.random_bytes(32)


def ctx(tenant="tenantA", field="name", row_id="row1", version=1):
    return nc.RecordContext(
        tenant.encode(), field.encode(), row_id.encode(), str(version).encode()
    )


SAMPLE_FIELDS = [
    b"",
    b"metoprolol",
    "café / naïve — résumé".encode(),
    b'{"dose":"25mg","route":"PO"}',
    b"x" * 100_000,
    bytes(range(256)),
]


# ---- 1. round-trip fidelity --------------------------------------------------

@pytest.mark.parametrize("plaintext", SAMPLE_FIELDS)
def test_round_trip_is_byte_exact(plaintext):
    rec = nc.seal(plaintext, USER_A, SYS_A, ctx())
    assert nc.open_record(rec, USER_A, SYS_A, ctx()) == plaintext


# ---- 2. server-blind at rest -------------------------------------------------

def test_sealed_bytes_contain_no_plaintext():
    secret = b"WARFARIN-5MG-DAILY-SENTINEL"
    rec = nc.seal(secret, USER_A, SYS_A, ctx())
    blob = rec.to_bytes()
    assert secret not in blob
    assert nc.open_record(nc.SealedRecord.from_bytes(blob), USER_A, SYS_A, ctx()) == secret


# ---- 3. dual-key enforcement: BOTH shares required ---------------------------

def test_open_fails_with_only_user_share():
    rec = nc.seal(b"secret", USER_A, SYS_A, ctx())
    with pytest.raises(InvalidTag):
        nc.open_record(rec, USER_A, nc.random_bytes(32), ctx())


def test_open_fails_with_only_system_share():
    rec = nc.seal(b"secret", USER_A, SYS_A, ctx())
    with pytest.raises(InvalidTag):
        nc.open_record(rec, nc.random_bytes(32), SYS_A, ctx())


def test_open_succeeds_only_with_both():
    rec = nc.seal(b"secret", USER_A, SYS_A, ctx())
    assert nc.open_record(rec, USER_A, SYS_A, ctx()) == b"secret"


# ---- 3b. empty/short shares fail closed (the fail-open break) -----------------

@pytest.mark.parametrize("bad", [b"", b"short", bytes(31), bytes(33), None])
def test_seal_rejects_bad_user_share(bad):
    with pytest.raises(ValueError):
        nc.seal(b"x", bad, SYS_A, ctx())


@pytest.mark.parametrize("bad", [b"", b"short", bytes(31)])
def test_seal_rejects_bad_system_share(bad):
    with pytest.raises(ValueError):
        nc.seal(b"x", USER_A, bad, ctx())


def test_derive_kek_rejects_empty_shares():
    with pytest.raises(ValueError):
        nc.derive_kek(b"", b"")


# ---- 4. recovery -------------------------------------------------------------

def test_recovery_code_reconstructs_access():
    salt = nc.random_bytes(16)
    code = nc.generate_recovery_code()
    us = nc.user_share_from_recovery_code(code, salt)
    rec = nc.seal(b"my notebook", us, SYS_A, ctx())
    again = nc.user_share_from_recovery_code(code, salt)
    assert nc.open_record(rec, again, SYS_A, ctx()) == b"my notebook"


def test_wrong_recovery_code_fails_closed():
    salt = nc.random_bytes(16)
    us = nc.user_share_from_recovery_code(nc.generate_recovery_code(), salt)
    rec = nc.seal(b"my notebook", us, SYS_A, ctx())
    wrong = nc.user_share_from_recovery_code(nc.generate_recovery_code(), salt)
    with pytest.raises(InvalidTag):
        nc.open_record(rec, wrong, SYS_A, ctx())


def test_recovery_code_whitespace_artifact_is_rejected_not_silently_wrong():
    salt = nc.random_bytes(16)
    code = nc.generate_recovery_code()
    clean = nc.user_share_from_recovery_code(code, salt)
    # trailing newline / spaces must be tolerated (same share), not mis-derived
    assert nc.user_share_from_recovery_code(code + "\n", salt) == clean
    assert nc.user_share_from_recovery_code("  " + code + " ", salt) == clean
    # a truly malformed code raises distinctly
    with pytest.raises(nc.MalformedRecoveryCode):
        nc.user_share_from_recovery_code("not-a-valid-code!!", salt)


# ---- 5. blind index: dual-share, deterministic, isolated ---------------------

def test_blind_index_is_deterministic_within_a_user():
    k = nc.derive_bi_key(USER_A, SYS_A)
    assert nc.blind_index(k, "Metoprolol") == nc.blind_index(k, "  metoprolol ")


def test_blind_index_differs_for_different_names():
    k = nc.derive_bi_key(USER_A, SYS_A)
    assert nc.blind_index(k, "metoprolol") != nc.blind_index(k, "metformin")


def test_same_name_across_users_yields_different_index():
    ka = nc.derive_bi_key(USER_A, SYS_A)
    kb = nc.derive_bi_key(USER_B, SYS_B)
    assert nc.blind_index(ka, "metoprolol") != nc.blind_index(kb, "metoprolol")


def test_blind_index_needs_both_shares():
    with pytest.raises(ValueError):
        nc.derive_bi_key(b"", SYS_A)
    with pytest.raises(ValueError):
        nc.derive_bi_key(USER_A, b"")


def test_canonicalization_folds_unicode_variants():
    k = nc.derive_bi_key(USER_A, SYS_A)
    # NFC vs NFD spelling of the same accented name
    assert nc.blind_index(k, "café") == nc.blind_index(k, "café")
    # fullwidth + zero-width joiner + casefold
    assert nc.blind_index(k, "Ｍｅ‍toprolol") == nc.blind_index(k, "metoprolol")


# ---- 6. tamper + substitution + rollback -------------------------------------

def test_tampered_ciphertext_is_rejected():
    rec = nc.seal(b"secret", USER_A, SYS_A, ctx())
    flipped = bytearray(rec.field_ct)
    flipped[0] ^= 0x01
    bad = nc.SealedRecord(rec.wrapped_dek_nonce, rec.wrapped_dek, rec.field_nonce, bytes(flipped))
    with pytest.raises(InvalidTag):
        nc.open_record(bad, USER_A, SYS_A, ctx())


def test_ciphertext_cannot_be_substituted_into_another_row():
    # THE clinical-safety break: swap a whole sealed blob onto a different row.
    rec_x = nc.seal(b"warfarin", USER_A, SYS_A, ctx(row_id="rowX"))
    with pytest.raises(InvalidTag):
        nc.open_record(rec_x, USER_A, SYS_A, ctx(row_id="rowY"))  # opened at another row → fails


def test_ciphertext_cannot_be_rolled_back_to_an_old_version():
    old = nc.seal(b"50mg", USER_A, SYS_A, ctx(field="dose", version=1))
    with pytest.raises(InvalidTag):
        nc.open_record(old, USER_A, SYS_A, ctx(field="dose", version=2))  # stale version → fails


def test_ciphertext_cannot_be_moved_between_fields():
    rec = nc.seal(b"secret", USER_A, SYS_A, ctx(field="name"))
    with pytest.raises(InvalidTag):
        nc.open_record(rec, USER_A, SYS_A, ctx(field="synonyms"))


def test_ciphertext_cannot_be_substituted_across_tenants():
    # `tenant` is the sole barrier against cross-notebook substitution for one
    # user's two tenants under the SAME shares — so it must be load-bearing.
    rec = nc.seal(b"warfarin", USER_A, SYS_A, ctx(tenant="tenantA"))
    with pytest.raises(InvalidTag):
        nc.open_record(rec, USER_A, SYS_A, ctx(tenant="tenantB"))


def test_large_field_round_trips_no_silent_loss():
    # A field larger than any past internal size cap must still round-trip — a
    # write/read asymmetry would silently lose data (long clinical note, base64
    # image). Exercises just past the old 1 MiB boundary.
    for size in (1_048_560, 1_048_561, 2_000_000):
        big = b"z" * size
        rec = nc.seal(big, USER_A, SYS_A, ctx())
        blob = rec.to_bytes()
        assert nc.open_record(nc.SealedRecord.from_bytes(blob), USER_A, SYS_A, ctx()) == big


# ---- 7. cross-tenant ---------------------------------------------------------

def test_identical_plaintext_two_users_unequal_everything():
    rec_a = nc.seal(b"metoprolol", USER_A, SYS_A, ctx())
    rec_b = nc.seal(b"metoprolol", USER_B, SYS_B, ctx(tenant="tenantB"))
    assert rec_a.field_ct != rec_b.field_ct
    ka = nc.derive_bi_key(USER_A, SYS_A)
    kb = nc.derive_bi_key(USER_B, SYS_B)
    assert nc.blind_index(ka, "metoprolol") != nc.blind_index(kb, "metoprolol")


# ---- 8. malformed serialized input fails closed (no struct.error / DoS) -------

@pytest.mark.parametrize(
    "blob",
    [
        b"",
        b"\x00\x00\x00",              # truncated length prefix
        b"\x00\x00\x00\x05ab",         # length exceeds remaining
        b"\xff\xff\xff\xff",           # absurd length
        b"\x00\x00\x00\x01a" + b"\x00\x00\x00\x01b",  # too few parts + trailing shape
    ],
)
def test_from_bytes_rejects_malformed_input(blob):
    with pytest.raises(ValueError):
        nc.SealedRecord.from_bytes(blob)
