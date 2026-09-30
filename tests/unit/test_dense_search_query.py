"""Tests for the dense query (ADR-018) and its mapping onto the contract.

This file previously asserted `"embedding <=> $1::vector" in HYBRID_QUERY` — it
pinned asyncpg placeholder syntax in a project that uses psycopg, so the only
test covering the query guaranteed the shape that could never execute. Corrected
rather than deleted: the assertions move to the psycopg form and gain the
coverage that would have caught the other two defects.
"""

from __future__ import annotations

import pytest

from data_platform_rag.contracts import RetrievedChunk
from data_platform_rag.retrieval.dense_search import (
    DENSE_QUERY,
    build_dense_query,
    row_to_chunk,
)


def test_query_uses_psycopg_placeholders_not_asyncpg() -> None:
    """The defect this file used to enshrine."""
    for asyncpg_placeholder in ("$1", "$2", "$3"):
        assert asyncpg_placeholder not in DENSE_QUERY
    assert "%(query_vector)s" in DENSE_QUERY
    assert "%(collections)s" in DENSE_QUERY


def test_query_uses_pgvector_cosine() -> None:
    assert "embedding <=> %(query_vector)s::vector" in DENSE_QUERY


@pytest.mark.parametrize("sparse", ["tsquery", "ts_rank_cd", "content_tsv", "%(query_text)s"])
def test_query_has_no_sparse_side_and_takes_no_text(sparse: str) -> None:
    """ADR-018: cosine distance alone. No user text reaches SQL."""
    assert sparse not in DENSE_QUERY


@pytest.mark.parametrize(
    "column",
    ["source_project", "source_type", "source_path", "chunk_index", "token_count"],
)
def test_query_selects_every_field_the_contract_requires(column: str) -> None:
    """ChunkMetadata cannot be built without these five. The query returned two."""
    assert column in DENSE_QUERY


@pytest.mark.parametrize("column", ["source_anchor", "adr_id", "topic", "status", "keywords"])
def test_query_carries_optional_metadata_too(column: str) -> None:
    """source_anchor is what makes a citation point at a section, not a whole ADR."""
    assert column in DENSE_QUERY


def test_limit_comes_from_a_parameter_not_a_literal() -> None:
    """ADR-008 cannot tune what is hardcoded in SQL."""
    assert "LIMIT 20" not in DENSE_QUERY
    assert DENSE_QUERY.count("LIMIT %(top_k)s") == 1


@pytest.mark.parametrize("column", ["rrf_score", "sparse_score", "sparse_rank", "%(rrf_k)s"])
def test_query_returns_no_constant_columns(column: str) -> None:
    """Removed in ADR-019 Amendment 1: they held the rank, 0.0 and NULL for every chunk."""
    assert column not in DENSE_QUERY


def test_ordering_is_deterministic() -> None:
    """The final order is the dense rank, which already carries the id tiebreak."""
    assert "ORDER BY d.dense_rank ASC" in DENSE_QUERY


def test_build_dense_query_rejects_empty_collections() -> None:
    with pytest.raises(ValueError, match="At least one collection"):
        build_dense_query([])


def test_build_dense_query_rejects_unknown_collection() -> None:
    """An unknown name would filter to nothing and look like 'no matches'."""
    with pytest.raises(ValueError, match="Unknown collection"):
        build_dense_query(["decisions", "adrs"])


def test_build_dense_query_accepts_valid_collections() -> None:
    assert build_dense_query(["decisions"]) == DENSE_QUERY
    assert build_dense_query(["decisions", "architecture"]) == DENSE_QUERY


# ─── row → contract ──────────────────────────────────────────────────────────


def make_row(**overrides) -> dict:
    row = {
        "id": 42,
        "content": "Context. Decision. Consequences.",
        "collection": "decisions",
        "source_project": "sdd-kafka-snowflake-2",
        "source_type": "adr",
        "source_path": "docs/adr/0029_snowpipe.md",
        "source_anchor": "Alternatives considered",
        "adr_id": "ADR-0029",
        "topic": None,
        "status": None,
        "keywords": None,
        "chunk_index": 2,
        "token_count": 310,
        "dense_dist": 0.154,
        "dense_rank": 1,
    }
    row.update(overrides)
    return row


def test_row_to_chunk_builds_a_valid_contract() -> None:
    chunk = row_to_chunk(make_row())
    assert isinstance(chunk, RetrievedChunk)
    assert chunk.metadata.source_anchor == "Alternatives considered"
    assert chunk.metadata.token_count == 310
    assert chunk.dense_rank == 1
    assert chunk.dense_distance == 0.154


@pytest.mark.parametrize("missing", ["source_type", "chunk_index", "token_count"])
def test_row_to_chunk_raises_rather_than_inventing_a_field(missing: str) -> None:
    """A defaulted token_count would be a lie told inside a citation."""
    row = make_row()
    del row[missing]
    with pytest.raises(KeyError):
        row_to_chunk(row)


# ─── tie-breaking ────────────────────────────────────────────────────────────


def test_the_dense_ranking_breaks_ties_by_id() -> None:
    """ROW_NUMBER over a tied key is arbitrary: the rank would follow heap order.

    Found under ADR-015's OR query on the sparse side; kept for the dense side,
    which is now the only one.
    """
    assert "ROW_NUMBER() OVER (ORDER BY dense_dist ASC, id ASC)" in DENSE_QUERY
    assert "ORDER BY dense_dist ASC, id ASC\n  LIMIT" in DENSE_QUERY


def test_the_search_is_exact_not_an_index_scan() -> None:
    """A window over every candidate: exact kNN, so rankings are reproducible (ADR-018)."""
    candidates, _, _ = DENSE_QUERY.partition("dense_ranked AS (")
    assert "embedding <=> %(query_vector)s::vector AS dense_dist" in candidates
    assert "ORDER BY" not in candidates
