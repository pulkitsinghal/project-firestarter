"""End-to-end against a REAL seeded Postgres (the shadow instance), not in memory.

The "test with sample DBs, don't assume it just works" gate. Stores sealed
records + dual-share blind indexes in a real table and proves, against actual
storage: nothing plaintext at rest, dedup within a tenant, no cross-tenant
linkage, a full round-trip, and that a row-substituted ciphertext fails to open.

Skips if NOTEBOOK_CRYPTO_PG_DSN is unset. The runner points it at the shadow.
"""

from __future__ import annotations

import os

import pytest
from cryptography.exceptions import InvalidTag

import notebook_crypto as nc

DSN = os.environ.get("NOTEBOOK_CRYPTO_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="NOTEBOOK_CRYPTO_PG_DSN not set")

psycopg = pytest.importorskip("psycopg")


@pytest.fixture
def conn():
    c = psycopg.connect(DSN, connect_timeout=8)
    c.execute("CREATE SCHEMA IF NOT EXISTS crypto_harness")
    c.execute("DROP TABLE IF EXISTS crypto_harness.entities")
    c.execute(
        "CREATE TABLE crypto_harness.entities ("
        " tenant_key text NOT NULL,"
        " name_bidx  text NOT NULL,"
        " name_sealed bytea NOT NULL,"
        " UNIQUE (tenant_key, name_bidx))"
    )
    c.commit()
    try:
        yield c
    finally:
        c.execute("DROP SCHEMA IF EXISTS crypto_harness CASCADE")
        c.commit()
        c.close()


def _ctx(tenant, bidx):
    return nc.RecordContext(tenant.encode(), b"name", bidx.encode(), b"1")


def _store(conn, tenant, user_share, system_share, name):
    bidx = nc.blind_index(nc.derive_bi_key(user_share, system_share), name)
    sealed = nc.seal(name.encode(), user_share, system_share, _ctx(tenant, bidx)).to_bytes()
    conn.execute(
        "INSERT INTO crypto_harness.entities VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
        (tenant, bidx, sealed),
    )
    conn.commit()
    return bidx


def test_server_blind_at_rest(conn):
    ua, sa = nc.random_bytes(32), nc.random_bytes(32)
    _store(conn, "tenantA", ua, sa, "WARFARIN_SENTINEL")
    raw = bytes(conn.execute("SELECT name_sealed FROM crypto_harness.entities").fetchone()[0])
    assert b"WARFARIN_SENTINEL" not in raw
    dump = conn.execute(
        "SELECT string_agg(encode(name_sealed,'escape'),'') FROM crypto_harness.entities"
    ).fetchone()[0]
    assert "WARFARIN" not in (dump or "")


def test_dedup_within_tenant(conn):
    ua, sa = nc.random_bytes(32), nc.random_bytes(32)
    b1 = _store(conn, "tenantA", ua, sa, "Metoprolol")
    b2 = _store(conn, "tenantA", ua, sa, "  metoprolol ")
    assert b1 == b2
    n = conn.execute(
        "SELECT count(*) FROM crypto_harness.entities WHERE tenant_key='tenantA'"
    ).fetchone()[0]
    assert n == 1


def test_no_cross_tenant_linkage(conn):
    ua, sa = nc.random_bytes(32), nc.random_bytes(32)
    ub, sb = nc.random_bytes(32), nc.random_bytes(32)
    ba = _store(conn, "tenantA", ua, sa, "metoprolol")
    bb = _store(conn, "tenantB", ub, sb, "metoprolol")
    assert ba != bb


def test_full_round_trip_through_db(conn):
    ua, sa = nc.random_bytes(32), nc.random_bytes(32)
    bidx = _store(conn, "tenantA", ua, sa, "lisinopril")
    row = conn.execute(
        "SELECT name_sealed FROM crypto_harness.entities WHERE tenant_key='tenantA'"
    ).fetchone()
    rec = nc.SealedRecord.from_bytes(bytes(row[0]))
    assert nc.open_record(rec, ua, sa, _ctx("tenantA", bidx)) == b"lisinopril"


def test_stored_blob_cannot_be_replayed_to_another_row(conn):
    # pull a real stored blob and try to open it as if it were a different entity
    ua, sa = nc.random_bytes(32), nc.random_bytes(32)
    _store(conn, "tenantA", ua, sa, "warfarin")
    row = conn.execute("SELECT name_sealed FROM crypto_harness.entities").fetchone()
    rec = nc.SealedRecord.from_bytes(bytes(row[0]))
    with pytest.raises(InvalidTag):
        nc.open_record(rec, ua, sa, _ctx("tenantA", "some-other-row-bidx"))
