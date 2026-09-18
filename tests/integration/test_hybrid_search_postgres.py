"""Integration tests for hybrid retrieval against real Postgres.

Vectors are chosen by hand so the RRF arithmetic can be computed on paper and
asserted exactly, rather than eyeballed. No embedding model is loaded: `search`
takes a vector, which is precisely why it was split from `retrieve`.

Geometry of the fixture, with the query vector = e0:

    A  e0                    cosine distance 0.0   text: no match
    C  0.6*e0 + 0.8*e1       cosine distance 0.4   text: no match
    B  e1                    cosine distance 1.0   text: MATCHES

so the dense ranking is A, C, B and the sparse ranking is B alone.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from data_platform_rag.contracts import Chunk, ChunkMetadata, IndexedSnapshot
from data_platform_rag.indexer.writer import write_project
from data_platform_rag.retrieval.hybrid_search import RRF_K, search

DIM = 384
PROJECT = "sdd-kafka-snowflake-2"
QUERY_TEXT = "debezium snowflake"


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


def seed(conn, entries=FIXTURE) -> None:
    chunks, embeddings = [], []
    for index, (name, content, vector, collection) in enumerate(entries):
        chunks.append(
            Chunk(
                content=content,
                collection=collection,
                metadata=ChunkMetadata(
                    source_project=PROJECT,
                    source_type="adr",
                    source_path=f"docs/adr/{name}.md",
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


def run(conn, *, top_k=20, collections=None, text=QUERY_TEXT):
    return search(
        conn,
        query_text=text,
        query_vector=QUERY_VECTOR,
        collections=collections or ["decisions", "architecture"],
        top_k=top_k,
    )


def paths(chunks) -> list[str]:
    return [c.metadata.source_path for c in chunks]


def test_ranking_matches_rrf_computed_by_hand(conn) -> None:
    seed(conn)
    results = run(conn)

    # dense: A=1, C=2, B=3.  sparse: B=1.
    #   B = 1/(60+3) + 1/(60+1) = 0.032266   <- wins despite the worst distance
    #   A = 1/(60+1)            = 0.016393
    #   C = 1/(60+2)            = 0.016129
    assert paths(results) == ["docs/adr/B.md", "docs/adr/A.md", "docs/adr/C.md"]

    by_path = {c.metadata.source_path: c for c in results}
    assert by_path["docs/adr/B.md"].rrf_score == pytest.approx(
        1 / (RRF_K + 3) + 1 / (RRF_K + 1), abs=1e-9
    )
    assert by_path["docs/adr/A.md"].rrf_score == pytest.approx(1 / (RRF_K + 1), abs=1e-9)
    assert by_path["docs/adr/C.md"].rrf_score == pytest.approx(1 / (RRF_K + 2), abs=1e-9)


def test_a_sparse_only_chunk_gets_no_phantom_dense_contribution(conn) -> None:
    """ADR-003 Amendment 1, asserted rather than assumed.

    With top_k=2 the dense list is A and C, so B is ranked by the sparse side
    alone. Its score must be exactly the sparse contribution. The old
    COALESCE(rank, 999) form would have added 1/(60+999) = 0.000944 on top.
    """
    seed(conn)
    results = run(conn, top_k=2)

    b = next(c for c in results if c.metadata.source_path == "docs/adr/B.md")
    assert b.dense_rank is None
    assert b.sparse_rank == 1
    assert b.rrf_score == pytest.approx(1 / (RRF_K + 1), abs=1e-9)
    assert b.rrf_score != pytest.approx(1 / (RRF_K + 1) + 1 / (RRF_K + 999), abs=1e-9)


def test_dense_distance_is_real_even_for_a_sparse_only_match(conn) -> None:
    """The value exists for every candidate; only the rank is absent."""
    seed(conn)
    b = next(c for c in run(conn, top_k=2) if c.metadata.source_path == "docs/adr/B.md")
    assert b.dense_distance == pytest.approx(1.0, abs=1e-6)


def test_top_k_is_honoured_and_order_is_descending(conn) -> None:
    seed(conn)
    results = run(conn, top_k=2)
    assert len(results) <= 2
    scores = [c.rrf_score for c in results]
    assert scores == sorted(scores, reverse=True)


def test_retrieval_is_deterministic(conn) -> None:
    seed(conn)
    first = [c.id for c in run(conn)]
    second = [c.id for c in run(conn)]
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


def test_a_question_matching_no_text_still_returns_dense_results(conn) -> None:
    """The sparse side contributing nothing must not empty the result."""
    seed(conn)
    results = run(conn, text="zzzz nonexistentword")
    assert len(results) == 3
    assert all(c.sparse_rank is None for c in results)
    assert all(c.dense_rank is not None for c in results)


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
