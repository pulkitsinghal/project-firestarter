"""Integration tests against a live Postgres — gated on TEST_DATABASE_URL.

The default `make backend-test` (and `make precommit`) stays hermetic: with
TEST_DATABASE_URL unset these self-skip. Run them via `make backend-itest`
(needs `make up` + `make migrate`); CI passes TEST_DATABASE_URL so they run
against the migrated stack. This is a seed — grow it with real integration
coverage as your domain layer lands.
"""

from __future__ import annotations

import os

import psycopg
import pytest

DB_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DB_URL, reason="set TEST_DATABASE_URL to run (make backend-itest)"),
]


def test_migrated_schema_is_reachable() -> None:
    """The example `items` table exists and is queryable after migrations."""
    assert DB_URL is not None
    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM items;")
        row = cur.fetchone()
    assert row is not None and row[0] >= 0
