"""Tests for the hybrid query and its mapping onto the contract.

This file previously asserted `"embedding <=> $1::vector" in HYBRID_QUERY` — it
pinned asyncpg placeholder syntax in a project that uses psycopg, so the only
test covering the query guaranteed the shape that could never execute. Corrected
rather than deleted: the assertions move to the psycopg form and gain the
coverage that would have caught the other two defects.
"""

from __future__ import annotations

import pytest

from data_platform_rag.contracts import RetrievedChunk
from data_platform_rag.retrieval.hybrid_search import (
    HYBRID_QUERY,
    RRF_K,
    build_hybrid_query,
    row_to_chunk,
)


def test_query_uses_psycopg_placeholders_not_asyncpg() -> None:
    """The defect this file used to enshrine."""
    for asyncpg_placeholder in ("$1", "$2", "$3"):
        assert asyncpg_placeholder not in HYBRID_QUERY
    assert "%(query_vector)s" in HYBRID_QUERY
    assert "%(query_text)s" in HYBRID_QUERY
    assert "%(collections)s" in HYBRID_QUERY


def test_query_uses_pgvector_cosine_and_tsvector_rank() -> None:
    assert "embedding <=> %(query_vector)s::vector" in HYBRID_QUERY
    assert "ts_rank_cd(content_tsv" in HYBRID_QUERY


@pytest.mark.parametrize(
    "column",
    ["source_project", "source_type", "source_path", "chunk_index", "token_count"],
)
def test_query_selects_every_field_the_contract_requires(column: str) -> None:
    """ChunkMetadata cannot be built without these five. The query returned two."""
    assert column in HYBRID_QUERY


@pytest.mark.parametrize("column", ["source_anchor", "adr_id", "topic", "status", "keywords"])
def test_query_carries_optional_metadata_too(column: str) -> None:
    """source_anchor is what makes a citation point at a section, not a whole ADR."""
    assert column in HYBRID_QUERY


def test_limit_comes_from_a_parameter_not_a_literal() -> None:
    """ADR-008 cannot tune what is hardcoded in SQL."""
    assert "LIMIT 20" not in HYBRID_QUERY
    assert HYBRID_QUERY.count("LIMIT %(top_k)s") == 3


def test_missing_side_contributes_zero_not_a_sentinel_rank() -> None:
    """ADR-003 Amendment 1.

    The old form was COALESCE(rank, 999), giving 1/(60+999) = 0.000944 for a
    missing side — 5.8% of a rank-1 contribution, where ADR-003 specifies zero.
    """
    assert "999" not in HYBRID_QUERY
    assert HYBRID_QUERY.count("COALESCE(1.0 / (%(rrf_k)s +") == 2
    assert ", 0)" in HYBRID_QUERY


def test_ordering_is_deterministic() -> None:
    """Ties on rrf_score must not reorder between runs."""
    assert "ORDER BY rrf_score DESC, c.id ASC" in HYBRID_QUERY


def test_rrf_constant_matches_adr_003() -> None:
    assert RRF_K == 60


def test_build_hybrid_query_rejects_empty_collections() -> None:
    with pytest.raises(ValueError, match="At least one collection"):
        build_hybrid_query([])


def test_build_hybrid_query_rejects_unknown_collection() -> None:
    """An unknown name would filter to nothing and look like 'no matches'."""
    with pytest.raises(ValueError, match="Unknown collection"):
        build_hybrid_query(["decisions", "adrs"])


def test_build_hybrid_query_accepts_valid_collections() -> None:
    assert build_hybrid_query(["decisions"]) == HYBRID_QUERY
    assert build_hybrid_query(["decisions", "architecture"]) == HYBRID_QUERY


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
        "sparse_score": 0.0912,
        "dense_rank": 1,
        "sparse_rank": 4,
        "rrf_score": 0.0320,
    }
    row.update(overrides)
    return row


def test_row_to_chunk_builds_a_valid_contract() -> None:
    chunk = row_to_chunk(make_row())
    assert isinstance(chunk, RetrievedChunk)
    assert chunk.metadata.source_anchor == "Alternatives considered"
    assert chunk.metadata.token_count == 310
    assert chunk.dense_rank == 1
    assert chunk.sparse_rank == 4


def test_row_to_chunk_preserves_a_missing_side_as_none() -> None:
    """None means 'not in that side's top-k'. It must not become 0."""
    chunk = row_to_chunk(make_row(sparse_rank=None, sparse_score=0.0))
    assert chunk.sparse_rank is None
    assert chunk.sparse_score == 0.0


@pytest.mark.parametrize("missing", ["source_type", "chunk_index", "token_count"])
def test_row_to_chunk_raises_rather_than_inventing_a_field(missing: str) -> None:
    """A defaulted token_count would be a lie told inside a citation."""
    row = make_row()
    del row[missing]
    with pytest.raises(KeyError):
        row_to_chunk(row)


# ─── sparse side and tie-breaking ────────────────────────────────────────────


def test_sparse_tsquery_is_built_once_inside_candidates() -> None:
    """Computed once; every CTE below reads `sparse_score` by name."""
    assert HYBRID_QUERY.count("plainto_tsquery(") == 1
    candidates, _, rest = HYBRID_QUERY.partition("dense_ranked AS (")
    assert "plainto_tsquery(" in candidates
    assert "WHERE sparse_score > 0" in rest


def test_both_ranked_lists_break_ties_by_id() -> None:
    """ROW_NUMBER over a tied key is arbitrary: the rank would follow heap order.

    The final `ORDER BY rrf_score DESC, c.id ASC` cannot repair a rank that was
    already assigned arbitrarily one CTE earlier. Found under ADR-015's OR query,
    where q002's top two sparse hits tie at 1.5; kept after its rejection.
    """
    assert "ROW_NUMBER() OVER (ORDER BY dense_dist ASC, id ASC)" in HYBRID_QUERY
    assert "ROW_NUMBER() OVER (ORDER BY sparse_score DESC, id ASC)" in HYBRID_QUERY
    assert "ORDER BY dense_dist ASC, id ASC\n  LIMIT" in HYBRID_QUERY
    assert "ORDER BY sparse_score DESC, id ASC\n  LIMIT" in HYBRID_QUERY
