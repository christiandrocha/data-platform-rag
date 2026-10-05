"""Tests for pydantic contracts. Per ADR-010, contracts.py is the source of
truth for all inter-module data shapes.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from data_platform_rag.contracts import (
    AnswerResult,
    ChunkMetadata,
    IndexedSnapshot,
    IndexRunReport,
    IntentClassification,
    RAGASAggregate,
    RAGASReport,
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


# ─── AnswerResult (ADR-021) ──────────────────────────────────────────────────


def answer_result(**overrides) -> AnswerResult:
    fields = {
        "question": "Why one unified Lakeflow pipeline?",
        "failed": False,
        "output_class": "answer",
        "shown_text": "Because Unity Catalog attributes lineage by notebook path...",
        "sources": [],
        "generation": None,
        "system_prompt_version": "v1.1.0",
        "context_format_version": "v1.0.0",
        "latency_ms": 1523,
        "logged": True,
    }
    return AnswerResult(**(fields | overrides))


def test_answer_result_valid():
    result = answer_result()
    assert result.latency_ms == 1523
    assert result.fallback_fired is False
    assert result.trace_id is None


def test_answer_result_rejects_an_unknown_output_class():
    with pytest.raises(ValidationError):
        answer_result(output_class="partial")


def test_answer_result_rejects_negative_latency():
    with pytest.raises(ValidationError):
        answer_result(latency_ms=-1)


def test_answer_result_has_no_pre_adr_018_fields():
    """`intent`, `top_chunks` and `top_score` described stages that do not run."""
    assert {"intent", "top_chunks", "top_score", "fallback_fired"}.isdisjoint(
        AnswerResult.model_fields
    )


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


# ─── Corpus provenance (ADR-013) ─────────────────────────────────────────────


def _snapshot(**overrides):
    fields = {
        "source_project": "sdd-kafka-databricks",
        "repo_url": "https://github.com/christiandrocha/sdd-kafka-databricks",
        "commit_sha": "f" * 40,
        "file_count": 31,
        "manifest_created_at": datetime(2026, 9, 18, tzinfo=UTC),
        "manifest_schema_version": 1,
        "embedding_model": "BAAI/bge-small-en-v1.5",
        "embedding_dim": 384,
        "chunk_count": 168,
    }
    fields.update(overrides)
    return IndexedSnapshot(**fields)


def test_indexed_snapshot_accepts_a_full_sha():
    assert _snapshot().commit_sha == "f" * 40


@pytest.mark.parametrize("bad_sha", ["f" * 39, "f" * 41, "F" * 40, "zz" + "f" * 38, ""])
def test_indexed_snapshot_rejects_a_malformed_sha(bad_sha):
    """An abbreviated or upper-case SHA would not compare equal to the manifest's."""
    with pytest.raises(ValidationError):
        _snapshot(commit_sha=bad_sha)


def test_indexed_snapshot_rejects_an_unknown_project():
    with pytest.raises(ValidationError):
        _snapshot(source_project="data-platform-rag")


def test_indexed_snapshot_rejects_a_negative_chunk_count():
    with pytest.raises(ValidationError):
        _snapshot(chunk_count=-1)


def test_indexed_snapshot_allows_zero_chunks():
    """A project that yields no chunks is a data question, not a contract error."""
    assert _snapshot(chunk_count=0).chunk_count == 0


def test_indexed_snapshot_requires_a_model_name():
    """Empty would defeat the point: the column exists to identify the embedding space."""
    with pytest.raises(ValidationError):
        _snapshot(embedding_model="")


def test_is_current_for_requires_both_commit_and_model():
    snapshot = _snapshot()
    assert snapshot.is_current_for("f" * 40, "BAAI/bge-small-en-v1.5") is True
    assert snapshot.is_current_for("a" * 40, "BAAI/bge-small-en-v1.5") is False
    assert snapshot.is_current_for("f" * 40, "BAAI/bge-base-en-v1.5") is False


def test_index_run_report_sums_chunks_written():
    report = IndexRunReport(
        snapshot_root="/tmp/dpr-corpus-1",
        written=[
            _snapshot(chunk_count=168),
            _snapshot(source_project="sdd-kafka-snowflake-2", chunk_count=136),
        ],
        embedding_model="BAAI/bge-small-en-v1.5",
        duration_seconds=12.5,
    )
    assert report.chunks_written == 304


def test_index_run_report_defaults_to_nothing_done():
    """A --verify run reports in the same shape, with written empty."""
    report = IndexRunReport(
        snapshot_root="/tmp/dpr-corpus-1",
        embedding_model="BAAI/bge-small-en-v1.5",
        duration_seconds=0.1,
    )
    assert report.written == []
    assert report.skipped == []
    assert report.chunks_written == 0


# ─── RetrievedChunk after ADR-019 Amendment 1 ────────────────────────────────


def _meta():
    return ChunkMetadata(
        source_project="sdd-kafka-snowflake-2",
        source_type="adr",
        source_path="x.md",
        chunk_index=0,
        token_count=100,
    )


@pytest.mark.parametrize("removed", ["rrf_score", "sparse_score", "sparse_rank"])
def test_retrieved_chunk_rejects_a_removed_field(removed):
    """extra="forbid": a stale caller fails loudly instead of losing the value silently."""
    with pytest.raises(ValidationError):
        RetrievedChunk(
            id=1, content="x", metadata=_meta(), dense_distance=0.1, dense_rank=1,
            **{removed: 0.0},
        )


def test_retrieved_chunk_requires_a_dense_rank():
    with pytest.raises(ValidationError):
        RetrievedChunk(id=1, content="x", metadata=_meta(), dense_distance=0.1)
    with pytest.raises(ValidationError):
        RetrievedChunk(id=1, content="x", metadata=_meta(), dense_distance=0.1, dense_rank=0)
