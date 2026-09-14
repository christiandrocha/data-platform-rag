# Pydantic models in data-platform-rag

All models live in `data_platform_rag/contracts.py`. This is the single import path
for any typed contract in the project.

## Core models

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Collection = Literal["decisions", "architecture"]
SourceProject = Literal["sdd-kafka-snowflake-2", "sdd-kafka-databricks"]
SourceType = Literal["adr", "readme", "contract", "macro", "schema"]
Intent = Literal["decision", "architecture", "comparison", "hybrid"]


class ChunkMetadata(BaseModel):
    """Structural metadata attached to every chunk. Written at index time."""
    model_config = ConfigDict(frozen=True)

    source_project: SourceProject
    source_type: SourceType
    source_path: str
    source_anchor: str | None = None
    adr_id: str | None = None
    topic: str | None = None
    status: Literal["accepted", "superseded", "resolved", "planned"] | None = None
    keywords: list[str] | None = None
    chunk_index: int = Field(ge=0)
    token_count: int = Field(gt=0)


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
    """RetrievedChunk augmented with cross-encoder score."""
    rerank_score: float


class IntentClassification(BaseModel):
    """Output of the intent classifier LLM call."""
    model_config = ConfigDict(frozen=True)

    intent: Intent
    collections: list[Collection] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


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


class RAGASReport(BaseModel):
    """Aggregate output of make eval — one row per golden-set question."""
    model_config = ConfigDict(frozen=True)

    question_id: str
    faithfulness: float = Field(ge=0.0, le=1.0)
    answer_relevance: float = Field(ge=0.0, le=1.0)
    context_precision: float = Field(ge=0.0, le=1.0)
    context_recall: float = Field(ge=0.0, le=1.0)
    fallback_correct: bool
```

## Where each model is used

| Model | Written by | Read by |
|-------|-----------|---------|
| ChunkMetadata | indexer/writer.py | retrieval/hybrid_search.py, UI |
| RetrievedChunk | retrieval/hybrid_search.py | retrieval/reranker.py |
| RerankedChunk | retrieval/reranker.py | generation/client.py, UI |
| IntentClassification | retrieval/intent_classifier.py | pipeline orchestration |
| AnswerResult | generation/pipeline.py | UI, Langfuse trace metadata |
| RAGASReport | evaluation/ragas_runner.py | CI, dashboard, Langfuse scores |
