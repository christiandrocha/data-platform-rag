"""Integration tests for replace-by-scope writing. Implements ADR-013's claims.

Every assertion here is about a property the DESIGN claims the *database*
enforces, not one the writer remembers to maintain. Where a test could be
written either as "the writer refuses" or "Postgres rejects", it is written as
the latter — that is the difference the composite foreign key buys.

Vectors are deterministic fakes. This suite is about transactions, cascades and
constraints; nothing here depends on the vectors meaning anything.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from data_platform_rag.contracts import Chunk, ChunkMetadata, IndexedSnapshot
from data_platform_rag.indexer.writer import (
    DimensionMismatch,
    current_snapshots,
    write_project,
)

DIM = 384
SHA_A = "a" * 40
SHA_B = "b" * 40
MODEL = "BAAI/bge-small-en-v1.5"


def make_chunks(project: str, n: int, source_type: str = "adr") -> list[Chunk]:
    return [
        Chunk(
            content=f"{project} chunk {i}. Context, decision, consequences.",
            collection="decisions" if source_type == "adr" else "architecture",
            metadata=ChunkMetadata(
                source_project=project,
                source_type=source_type,
                source_path=f"docs/adr/ADR-{i:04d}.md",
                chunk_index=0,
                token_count=9,
            ),
        )
        for i in range(n)
    ]


def make_snapshot(project: str, sha: str, chunk_count: int, model: str = MODEL) -> IndexedSnapshot:
    return IndexedSnapshot(
        source_project=project,
        repo_url=f"https://github.com/christiandrocha/{project}",
        commit_sha=sha,
        file_count=max(chunk_count, 1),
        manifest_created_at=datetime(2026, 9, 18, tzinfo=UTC),
        manifest_schema_version=1,
        embedding_model=model,
        embedding_dim=DIM,
        chunk_count=chunk_count,
    )


def vectors(n: int) -> list[list[float]]:
    return [[float(i % 7) / 10.0] * DIM for i in range(n)]


def count_chunks(conn, project: str | None = None) -> int:
    with conn.cursor() as cur:
        if project is None:
            cur.execute("SELECT count(*) FROM chunks")
        else:
            cur.execute("SELECT count(*) FROM chunks WHERE source_project = %s", (project,))
        return cur.fetchone()[0]


def test_write_populates_chunks_and_provenance(conn) -> None:
    chunks = make_chunks("sdd-kafka-databricks", 5)
    snapshot = make_snapshot("sdd-kafka-databricks", SHA_A, 5)
    written = write_project(conn, snapshot, chunks, vectors(5))

    assert written == 5
    assert count_chunks(conn) == 5

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM chunks WHERE embedding IS NULL")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT DISTINCT vector_dims(embedding) FROM chunks")
        assert cur.fetchall() == [(DIM,)]

    indexed = current_snapshots(conn)
    assert indexed["sdd-kafka-databricks"].commit_sha == SHA_A
    assert indexed["sdd-kafka-databricks"].chunk_count == 5


def test_generated_tsvector_is_populated(conn) -> None:
    """content_tsv is GENERATED ALWAYS; the writer must not try to supply it."""
    chunks = make_chunks("sdd-kafka-databricks", 2)
    write_project(conn, make_snapshot("sdd-kafka-databricks", SHA_A, 2), chunks, vectors(2))
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM chunks WHERE content_tsv IS NULL")
        assert cur.fetchone()[0] == 0


def test_rerunning_is_idempotent(conn) -> None:
    """Twice over the same input is the same table, not double the rows."""
    for _ in range(2):
        chunks = make_chunks("sdd-kafka-databricks", 4)
        write_project(
            conn, make_snapshot("sdd-kafka-databricks", SHA_A, 4), chunks, vectors(4)
        )
    assert count_chunks(conn) == 4
    assert len(current_snapshots(conn)) == 1


def test_replace_by_scope_leaves_no_orphans(conn) -> None:
    """The case upsert gets wrong: a later commit produces FEWER chunks.

    An `ON CONFLICT DO UPDATE` would update 3 rows and leave rows 4 and 5 behind,
    retrievable, citing a path whose content no longer includes them.
    """
    write_project(
        conn,
        make_snapshot("sdd-kafka-databricks", SHA_A, 5),
        make_chunks("sdd-kafka-databricks", 5),
        vectors(5),
    )
    write_project(
        conn,
        make_snapshot("sdd-kafka-databricks", SHA_B, 3),
        make_chunks("sdd-kafka-databricks", 3),
        vectors(3),
    )

    assert count_chunks(conn) == 3
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT commit_sha FROM corpus_snapshot")
        assert cur.fetchall() == [(SHA_B,)]


def test_one_project_does_not_disturb_the_other(conn) -> None:
    write_project(
        conn,
        make_snapshot("sdd-kafka-databricks", SHA_A, 4),
        make_chunks("sdd-kafka-databricks", 4),
        vectors(4),
    )
    write_project(
        conn,
        make_snapshot("sdd-kafka-snowflake-2", SHA_B, 2),
        make_chunks("sdd-kafka-snowflake-2", 2),
        vectors(2),
    )
    # Rewrite only the first project.
    write_project(
        conn,
        make_snapshot("sdd-kafka-databricks", SHA_B, 1),
        make_chunks("sdd-kafka-databricks", 1),
        vectors(1),
    )

    assert count_chunks(conn, "sdd-kafka-databricks") == 1
    assert count_chunks(conn, "sdd-kafka-snowflake-2") == 2


def test_deleting_a_snapshot_cascades_to_its_chunks(conn) -> None:
    write_project(
        conn,
        make_snapshot("sdd-kafka-databricks", SHA_A, 3),
        make_chunks("sdd-kafka-databricks", 3),
        vectors(3),
    )
    write_project(
        conn,
        make_snapshot("sdd-kafka-snowflake-2", SHA_A, 2),
        make_chunks("sdd-kafka-snowflake-2", 2),
        vectors(2),
    )
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM corpus_snapshot WHERE source_project = %s",
            ("sdd-kafka-databricks",),
        )
    conn.commit()

    assert count_chunks(conn, "sdd-kafka-databricks") == 0
    assert count_chunks(conn, "sdd-kafka-snowflake-2") == 2


def test_database_rejects_a_chunk_whose_project_disagrees(conn) -> None:
    """What the composite foreign key buys, asserted against Postgres itself."""
    import psycopg

    write_project(
        conn,
        make_snapshot("sdd-kafka-databricks", SHA_A, 1),
        make_chunks("sdd-kafka-databricks", 1),
        vectors(1),
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM corpus_snapshot WHERE source_project = %s",
            ("sdd-kafka-databricks",),
        )
        snapshot_id = cur.fetchone()[0]

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO chunks (collection, content, embedding, source_project, "
                    "source_type, source_path, chunk_index, token_count, snapshot_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        "decisions",
                        "a chunk lying about its project",
                        "[" + ",".join(["0.0"] * DIM) + "]",
                        "sdd-kafka-snowflake-2",  # disagrees with snapshot_id's project
                        "adr",
                        "docs/adr/ADR-0001.md",
                        0,
                        5,
                        snapshot_id,
                    ),
                )


def test_a_failure_mid_write_leaves_the_previous_rows(conn) -> None:
    """The failure mode `make reindex` used to have: destroy, then fail, leaving 0.

    The delete and the insert share a transaction, so a failure after the delete
    rolls the delete back too.
    """
    write_project(
        conn,
        make_snapshot("sdd-kafka-databricks", SHA_A, 4),
        make_chunks("sdd-kafka-databricks", 4),
        vectors(4),
    )
    assert count_chunks(conn) == 4

    bad = vectors(4)
    bad[2] = [0.0] * 383
    with pytest.raises(DimensionMismatch):
        write_project(
            conn,
            make_snapshot("sdd-kafka-databricks", SHA_B, 4),
            make_chunks("sdd-kafka-databricks", 4),
            bad,
        )

    assert count_chunks(conn) == 4
    assert current_snapshots(conn)["sdd-kafka-databricks"].commit_sha == SHA_A


def test_snapshot_chunk_count_must_match_what_is_written(conn) -> None:
    """The provenance row must describe the rows it is written with."""
    with pytest.raises(ValueError, match="chunk_count"):
        write_project(
            conn,
            make_snapshot("sdd-kafka-databricks", SHA_A, 99),
            make_chunks("sdd-kafka-databricks", 3),
            vectors(3),
        )
    assert count_chunks(conn) == 0


def test_current_snapshots_is_empty_on_a_fresh_database(conn) -> None:
    assert current_snapshots(conn) == {}


def test_short_circuit_key_includes_the_model(conn) -> None:
    """Same commit, different model, must not count as up to date."""
    write_project(
        conn,
        make_snapshot("sdd-kafka-databricks", SHA_A, 2),
        make_chunks("sdd-kafka-databricks", 2),
        vectors(2),
    )
    indexed = current_snapshots(conn)["sdd-kafka-databricks"]
    assert indexed.is_current_for(SHA_A, MODEL) is True
    assert indexed.is_current_for(SHA_A, "some/other-model") is False
    assert indexed.is_current_for(SHA_B, MODEL) is False
