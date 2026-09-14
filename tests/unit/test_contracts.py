"""Tests for pydantic contracts. Per ADR-010, contracts.py is the source of
truth for all inter-module data shapes.
"""

import pytest
from pydantic import ValidationError

from data_platform_rag.contracts import (
    AnswerResult,
    ChunkMetadata,
    IntentClassification,
    RAGASAggregate,
    RAGASReport,
    RerankedChunk,
    RetrievedChunk,
)

# ─── ChunkMetadata ───────────────────────────────────────────────────────────


def test_chunk_metadata_valid():
    m = ChunkMetadata(
        source_project="sdd-kafka-snowflake-2",
        source_type="adr",
        source_path="docs/adr/ADR-0019.md",
        adr_id="ADR-0019",
        topic="cost-governance",
        status="accepted",
        chunk_index=0,
        token_count=1200,
    )
    assert m.source_project == "sdd-kafka-snowflake-2"
    assert m.status == "accepted"


def test_chunk_metadata_rejects_invalid_project():
    with pytest.raises(ValidationError):
        ChunkMetadata(
            source_project="some-random-repo",  # not in Literal
            source_type="adr",
            source_path="x",
            chunk_index=0,
            token_count=100,
        )


def test_chunk_metadata_rejects_negative_chunk_index():
    with pytest.raises(ValidationError):
        ChunkMetadata(
            source_project="sdd-kafka-databricks",
            source_type="readme",
            source_path="README.md",
            chunk_index=-1,
            token_count=100,
        )


def test_chunk_metadata_is_frozen():
    m = ChunkMetadata(
        source_project="sdd-kafka-databricks",
        source_type="contract",
        source_path="contracts/x.yml",
        chunk_index=0,
        token_count=50,
    )
    with pytest.raises(ValidationError):
        m.chunk_index = 999


# ─── IntentClassification ────────────────────────────────────────────────────


def test_intent_classification_requires_at_least_one_collection():
    with pytest.raises(ValidationError):
        IntentClassification(intent="decision", collections=[], confidence=0.9)


def test_intent_classification_confidence_bounded():
    with pytest.raises(ValidationError):
        IntentClassification(intent="decision", collections=["decisions"], confidence=1.5)


def test_intent_classification_rejects_unknown_collection():
    with pytest.raises(ValidationError):
        IntentClassification(
            intent="decision", collections=["methodology"], confidence=0.5  # rejected in ADR-002
        )


# ─── RetrievedChunk / RerankedChunk inheritance ──────────────────────────────


def test_reranked_chunk_extends_retrieved_chunk():
    meta = ChunkMetadata(
        source_project="sdd-kafka-snowflake-2",
        source_type="adr",
        source_path="x.md",
        chunk_index=0,
        token_count=100,
    )
    rc = RerankedChunk(
        id=1,
        content="foo",
        metadata=meta,
        dense_distance=0.1,
        sparse_score=0.2,
        rrf_score=0.3,
        rerank_score=0.9,
    )
    assert isinstance(rc, RetrievedChunk)
    assert rc.rerank_score == 0.9


# ─── AnswerResult ────────────────────────────────────────────────────────────


def test_answer_result_valid():
    meta = ChunkMetadata(
        source_project="sdd-kafka-databricks",
        source_type="adr",
        source_path="docs/adr/ADR-007.md",
        chunk_index=0,
        token_count=500,
    )
    reranked = [
        RerankedChunk(
            id=42, content="x", metadata=meta,
            dense_distance=0.1, sparse_score=0.2, rrf_score=0.3, rerank_score=0.95,
        )
    ]
    result = AnswerResult(
        query="Why one unified Lakeflow pipeline?",
        intent=IntentClassification(
            intent="decision", collections=["decisions"], confidence=0.87
        ),
        top_chunks=reranked,
        top_score=0.95,
        fallback_fired=False,
        answer_text="Because Unity Catalog attributes lineage by notebook path...",
        latency_ms=1523,
    )
    assert result.latency_ms == 1523
    assert result.fallback_fired is False


# ─── RAGAS ──────────────────────────────────────────────────────────────────


def test_ragas_report_bounded():
    with pytest.raises(ValidationError):
        RAGASReport(
            question_id="q001",
            faithfulness=1.1,  # > 1.0
            answer_relevance=0.8,
            context_precision=0.7,
            context_recall=0.9,
            fallback_correct=True,
        )


def test_ragas_aggregate_requires_positive_n():
    with pytest.raises(ValidationError):
        RAGASAggregate(
            n_questions=0,  # gt=0
            faithfulness_mean=0.8,
            answer_relevance_mean=0.8,
            context_precision_mean=0.8,
            context_recall_mean=0.8,
            fallback_accuracy=1.0,
            reports=[],
        )
