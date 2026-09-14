"""Pydantic v2 contracts for all inter-module boundaries in data-platform-rag.

Per ADR-010, this is the single source of truth for data crossing module
boundaries. No dict[str, Any] in public APIs. Every new boundary starts here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ─── Type aliases ────────────────────────────────────────────────────────────

Collection = Literal["decisions", "architecture"]
SourceProject = Literal["sdd-kafka-snowflake-2", "sdd-kafka-databricks"]
SourceType = Literal["adr", "readme", "contract", "macro", "schema"]
Intent = Literal["decision", "architecture", "hybrid"]
ADRStatus = Literal["accepted", "superseded", "resolved", "planned"]


# ─── Chunk metadata (written at index time) ──────────────────────────────────


class ChunkMetadata(BaseModel):
    """Structural metadata attached to every chunk."""

    model_config = ConfigDict(frozen=True)

    source_project: SourceProject
    source_type: SourceType
    source_path: str
    source_anchor: str | None = None
    adr_id: str | None = None
    topic: str | None = None
    status: ADRStatus | None = None
    chunk_index: int = Field(ge=0)
    token_count: int = Field(gt=0)


# ─── Retrieval results ───────────────────────────────────────────────────────


class RetrievedChunk(BaseModel):
    """A chunk returned by hybrid retrieval, before reranking."""

    model_config = ConfigDict(frozen=True)

    id: int
    content: str
    metadata: ChunkMetadata
    dense_distance: float = Field(ge=0.0)
    sparse_score: float = Field(ge=0.0)
    rrf_score: float = Field(ge=0.0)


class RerankedChunk(RetrievedChunk):
    """RetrievedChunk augmented with cross-encoder rerank score."""

    rerank_score: float


# ─── Intent classification ───────────────────────────────────────────────────


class IntentClassification(BaseModel):
    """Output of the intent classifier LLM call."""

    model_config = ConfigDict(frozen=True)

    intent: Intent
    collections: list[Collection] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


# ─── Final query result ──────────────────────────────────────────────────────


class AnswerResult(BaseModel):
    """The final result of a query, whether answered or fallback-fired."""

    model_config = ConfigDict(frozen=True)

    query: str
    intent: IntentClassification
    top_chunks: list[RerankedChunk]
    top_score: float
    fallback_fired: bool
    answer_text: str
    langfuse_trace_id: str | None = None
    latency_ms: int = Field(ge=0)


# ─── RAGAS evaluation ────────────────────────────────────────────────────────


class RAGASReport(BaseModel):
    """One row per golden-set question after make eval."""

    model_config = ConfigDict(frozen=True)

    question_id: str
    faithfulness: float = Field(ge=0.0, le=1.0)
    answer_relevance: float = Field(ge=0.0, le=1.0)
    context_precision: float = Field(ge=0.0, le=1.0)
    context_recall: float = Field(ge=0.0, le=1.0)
    fallback_correct: bool


class RAGASAggregate(BaseModel):
    """Aggregate RAGAS metrics across the whole golden set. What CI reports."""

    model_config = ConfigDict(frozen=True)

    n_questions: int = Field(gt=0)
    faithfulness_mean: float = Field(ge=0.0, le=1.0)
    answer_relevance_mean: float = Field(ge=0.0, le=1.0)
    context_precision_mean: float = Field(ge=0.0, le=1.0)
    context_recall_mean: float = Field(ge=0.0, le=1.0)
    fallback_accuracy: float = Field(ge=0.0, le=1.0)
    reports: list[RAGASReport]
