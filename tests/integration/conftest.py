"""Shared fixtures for tests that need a real Postgres with pgvector.

**These tests never touch the configured database.** An earlier version of this
file truncated whatever `DATABASE_URL` pointed at, which on a developer machine
is the local index — so `make test` silently destroyed the corpus that
`make index-corpus` had just written, and the damage was only visible later, as
an empty `make verify-indexes` baseline.

Instead, every run gets a dedicated database named after the configured one with
`_test` appended, created on demand and built from the same `sql/` files as
production. Isolation is structural: there is no code path here that can name the
real database.

They skip rather than fail when no server is reachable: `make test` has to stay
runnable in a bare checkout and in CI, where slice 1 established that the suite
needs no network and no services.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from data_platform_rag.config import Settings

DSN_ENV = "DATABASE_URL"
TEST_DB_SUFFIX = "_test"

# The same files `make bootstrap` runs, in the same order. 90_reset.sql is
# deliberately absent: the fixture creates a fresh database instead of dropping.
SCHEMA_FILES = (
    "sql/00_extensions.sql",
    "sql/01_schema.sql",
    "sql/02_indexes.sql",
    "sql/03_corpus_snapshot.sql",
)


def _configured_dsn() -> str | None:
    dsn = os.environ.get(DSN_ENV)
    if dsn:
        return dsn
    try:
        return str(Settings().database_url)
    except Exception:
        return None


def _split_dsn(dsn: str) -> tuple[str, str]:
    """Return (dsn without the database name, database name)."""
    base, _, database = dsn.rpartition("/")
    database, _, _ = database.partition("?")
    return base, database


@pytest.fixture(scope="session")
def test_dsn() -> str:
    """A dedicated `<configured>_test` database, created and migrated on demand."""
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("pgvector")

    configured = _configured_dsn()
    if configured is None:
        pytest.skip(f"{DSN_ENV} is not configured")

    base, database = _split_dsn(configured)
    if database.endswith(TEST_DB_SUFFIX):
        pytest.skip(
            f"{DSN_ENV} already points at a {TEST_DB_SUFFIX} database; refusing to "
            f"derive another and risk pointing at something a person cares about"
        )
    test_database = f"{database}{TEST_DB_SUFFIX}"
    admin_dsn = f"{base}/postgres"
    target_dsn = f"{base}/{test_database}"

    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (test_database,))
            if cur.fetchone() is None:
                # Identifier, not a value, so it cannot be parameterised. The name
                # is derived from config and suffixed here, never from test input.
                cur.execute(f'CREATE DATABASE "{test_database}"')  # nosec B608
    except psycopg.Error as exc:
        pytest.skip(f"no Postgres server reachable: {exc}")

    root = Path(__file__).resolve().parents[2]
    with psycopg.connect(target_dsn, autocommit=True) as conn, conn.cursor() as cur:
        for relative in SCHEMA_FILES:
            cur.execute((root / relative).read_text())

    return target_dsn


@pytest.fixture
def conn(test_dsn: str):
    """A connection to the test database, with its corpus tables empty.

    Truncating `corpus_snapshot` cascades into `chunks`, which is the same
    mechanism replace-by-scope relies on — so the fixture exercises it on every
    setup, and a broken cascade would show up as leftover rows here first.
    """
    from data_platform_rag.indexer.writer import connect

    connection = connect(test_dsn)
    with connection:
        with connection.cursor() as cur:
            cur.execute("TRUNCATE corpus_snapshot CASCADE")
        connection.commit()
        yield connection
        connection.rollback()
        with connection.cursor() as cur:
            cur.execute("TRUNCATE corpus_snapshot CASCADE")
        connection.commit()
