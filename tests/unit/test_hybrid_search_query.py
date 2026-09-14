"""Tests for the hybrid query SQL builder."""

import pytest

from data_platform_rag.retrieval.hybrid_search import HYBRID_QUERY, build_hybrid_query


def test_hybrid_query_contains_rrf_formula():
    assert "1.0 / (60 +" in HYBRID_QUERY
    assert "dense_rank" in HYBRID_QUERY
    assert "sparse_rank" in HYBRID_QUERY


def test_hybrid_query_uses_pgvector_cosine():
    assert "embedding <=> $1::vector" in HYBRID_QUERY


def test_hybrid_query_uses_tsvector_rank():
    assert "ts_rank_cd(content_tsv" in HYBRID_QUERY


def test_hybrid_query_limits_to_20_per_side():
    # Cover-and-rerank: 20 candidates each, 20 fused
    assert HYBRID_QUERY.count("LIMIT 20") == 3


def test_build_hybrid_query_rejects_empty_collections():
    with pytest.raises(ValueError):
        build_hybrid_query([])
