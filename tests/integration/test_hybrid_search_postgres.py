"""Integration tests for dense-only retrieval (ADR-018) against real Postgres.

Vectors are chosen by hand so the ranking and its scores can be computed on paper
and asserted exactly, rather than eyeballed. No embedding model is loaded:
`search` takes a vector, which is precisely why it was split from `retrieve`.

Geometry of the fixture, with the query vector = e0:

    A  e0                    cosine distance 0.0
    C  0.6*e0 + 0.8*e1       cosine distance 0.4
    B  e1                    cosine distance 1.0   text: "debezium snowflake ..."

so the ranking is A, C, B. Under ADR-003's fusion, B ranked first on the sparse
vote for the text "debezium snowflake". It now ranks by its distance alone.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from data_platform_rag.contracts import Chunk, ChunkMetadata, IndexedSnapshot
from data_platform_rag.indexer.writer import write_project
from data_platform_rag.retrieval.hybrid_search import RRF_K, search

DIM = 384
PROJECT = "sdd-kafka-snowflake-2"


def unit(*components: tuple[int, float]) -> list[float]:
    vector = [0.0] * DIM
    for index, value in components:
        vector[index] = value
    return vector


QUERY_VECTOR = unit((0, 1.0))
FIXTURE = [
    ("A", "alpha alpha alpha", unit((0, 1.0)), "decisions"),
    ("B", "debezium snowflake ingestion path", unit((1, 1.0)), "decisions"),
    ("C", "gamma gamma", unit((0, 0.6), (1, 0.8)), "decisions"),
]


def seed(conn, entries=FIXTURE, file_of=None) -> None:
    """Write the entries as one project. Each entry is its own file by default.

    `file_of` maps an entry name to a file name, to put several chunks in one
    file. Added for ADR-017, whose (rejected) cutoff was the chunk count of the
    largest file: any rule that counts per file needs fixtures that say which
    chunks share one.
    """
    file_of = file_of or {}
    chunks, embeddings = [], []
    for index, (name, content, vector, collection) in enumerate(entries):
        chunks.append(
            Chunk(
                content=content,
                collection=collection,
                metadata=ChunkMetadata(
                    source_project=PROJECT,
                    source_type="adr",
                    source_path=f"docs/adr/{file_of.get(name, name)}.md",
                    source_anchor=f"section {name}",
                    chunk_index=index,
                    token_count=4,
                ),
            )
        )
        embeddings.append(vector)

    snapshot = IndexedSnapshot(
        source_project=PROJECT,
        repo_url=f"https://github.com/christiandrocha/{PROJECT}",
        commit_sha="c" * 40,
        file_count=len(entries),
        manifest_created_at=datetime(2026, 9, 18, tzinfo=UTC),
        manifest_schema_version=1,
        embedding_model="fixture/hand-chosen",
        embedding_dim=DIM,
        chunk_count=len(chunks),
    )
    write_project(conn, snapshot, chunks, embeddings)


def run(conn, *, top_k=20, collections=None, vector=QUERY_VECTOR):
    return search(
        conn,
        query_vector=vector,
        collections=collections or ["decisions", "architecture"],
        top_k=top_k,
    )


def paths(chunks) -> list[str]:
    return [c.metadata.source_path for c in chunks]


def test_ranking_is_cosine_distance_alone(conn) -> None:
    """B contains the old query text word for word, and still ranks by its distance."""
    seed(conn)
    results = run(conn)

    assert paths(results) == ["docs/adr/A.md", "docs/adr/C.md", "docs/adr/B.md"]
    assert [c.dense_rank for c in results] == [1, 2, 3]
    assert [c.dense_distance for c in results] == pytest.approx([0.0, 0.4, 1.0], abs=1e-6)


def test_rrf_score_is_the_dense_only_contribution(conn) -> None:
    """1/(60 + dense_rank): what a dense-only chunk scored under the fusion (ADR-018)."""
    seed(conn)
    scores = [c.rrf_score for c in run(conn)]
    assert scores == pytest.approx([1 / (RRF_K + r) for r in (1, 2, 3)], abs=1e-9)


def test_no_chunk_carries_a_sparse_rank_or_score(conn) -> None:
    seed(conn)
    results = run(conn)
    assert all(c.sparse_rank is None for c in results)
    assert all(c.sparse_score == 0.0 for c in results)


def test_top_k_is_honoured_and_order_is_descending(conn) -> None:
    seed(conn)
    results = run(conn, top_k=2)
    assert paths(results) == ["docs/adr/A.md", "docs/adr/C.md"]
    scores = [c.rrf_score for c in results]
    assert scores == sorted(scores, reverse=True)


def test_retrieval_is_deterministic(conn) -> None:
    seed(conn)
    first = [(c.id, c.rrf_score) for c in run(conn)]
    second = [(c.id, c.rrf_score) for c in run(conn)]
    assert first == second


def test_collection_filter_excludes_the_other_collection(conn) -> None:
    seed(
        conn,
        [
            ("A", "alpha", unit((0, 1.0)), "decisions"),
            ("B", "debezium snowflake", unit((1, 1.0)), "architecture"),
        ],
    )
    decisions = run(conn, collections=["decisions"])
    assert {c.metadata.source_path for c in decisions} == {"docs/adr/A.md"}

    architecture = run(conn, collections=["architecture"])
    assert {c.metadata.source_path for c in architecture} == {"docs/adr/B.md"}


def test_empty_index_returns_an_empty_list(conn) -> None:
    """Not an exception: an unpopulated index is a state, not a failure."""
    assert run(conn) == []


def test_every_result_is_a_fully_populated_contract(conn) -> None:
    seed(conn)
    for chunk in run(conn):
        assert chunk.metadata.source_type == "adr"
        assert chunk.metadata.token_count > 0
        assert chunk.metadata.source_anchor is not None
        assert chunk.id > 0


def test_a_distance_tie_breaks_by_id_not_by_heap_order(conn) -> None:
    """Two chunks with identical vectors tie on distance; the lower id ranks first.

    The UPDATE rewrites the lower-id row at the end of the heap, so a sequential
    scan meets the higher id first. Without `id ASC` in the window, ROW_NUMBER
    would follow that order. Found on the sparse side under ADR-015; the dense
    side is now the only one.
    """
    seed(
        conn,
        [
            ("T1", "first", unit((0, 1.0)), "decisions"),
            ("T2", "second", unit((0, 1.0)), "decisions"),
        ],
    )
    with conn.cursor() as cur:
        cur.execute("SELECT min(id) FROM chunks")
        low = cur.fetchone()[0]
        cur.execute("UPDATE chunks SET token_count = token_count WHERE id = %s", (low,))

    first = run(conn)
    assert first[0].id == low
    assert [c.dense_rank for c in first] == [1, 2]
    assert [c.id for c in run(conn)] == [c.id for c in first]
