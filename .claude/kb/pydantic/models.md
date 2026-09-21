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
    # Which side ranked this chunk, and at what position. None means the chunk
    # was not in that side's top-k at all -- not the same as scoring zero there.
    dense_rank: int | None = Field(default=None, ge=1)
    sparse_rank: int | None = Field(default=None, ge=1)


class RerankedChunk(RetrievedChunk):
    """RetrievedChunk augmented with cross-encoder rerank score (ADR-005)."""
    rerank_score: float
    # True when (question, content) exceeded the model's window and was scored on
    # a truncated pair. Required, not defaulted: a default of False would assert
    # "not truncated" about a chunk nobody measured.
    truncated: bool


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
| CorpusFile / CorpusProject / CorpusManifest | scripts/fetch_corpus.py | indexer/corpus.py, scripts/index_corpus.py |
| IndexedSnapshot | indexer/writer.py | scripts/index_corpus.py (`--verify`, short-circuit) |
| IndexRunReport | scripts/index_corpus.py | the CLI's own output |
| Chunk | indexer/chunker.py | indexer/writer.py |
| ChunkMetadata | indexer/writer.py | retrieval/hybrid_search.py, UI |
| RetrievedChunk | retrieval/hybrid_search.py | retrieval/reranker.py |
| RerankedChunk | retrieval/reranker.py | generation/client.py, UI |
| IntentClassification | retrieval/intent_classifier.py | pipeline orchestration |
| AnswerResult | generation/pipeline.py | UI, Langfuse trace metadata |
| RAGASReport | evaluation/ragas_runner.py | CI, dashboard, Langfuse scores |


## Corpus provenance (ADR-013)

`CorpusManifest` is the on-disk record of a fetch; `IndexedSnapshot` is the
database's record of what was indexed from it. The pair is what makes
*indexed corpus == verified corpus* an executable comparison rather than a
promise, and `make index-corpus-verify` is that comparison.

```python
class IndexedSnapshot(BaseModel):
    """One project's provenance row, as written to corpus_snapshot."""
    model_config = ConfigDict(frozen=True)

    source_project: SourceProject
    repo_url: AnyUrl
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    file_count: int = Field(gt=0)
    manifest_created_at: datetime
    manifest_schema_version: int = Field(ge=1)
    embedding_model: str = Field(min_length=1)
    embedding_dim: int = Field(gt=0)
    chunk_count: int = Field(ge=0)

    def is_current_for(self, commit_sha: str, embedding_model: str) -> bool:
        ...
```

Two things about this model are load-bearing rather than decorative:

- **`embedding_model` is part of the identity of an index.** A `VECTOR(384)`
  column accepts vectors from any 384-dimensional model, so without this field a
  corpus embedded half with one model and half with another is indistinguishable
  from a healthy one. It is included in `is_current_for`, which is why changing
  `settings.embedding_model` forces a re-embed instead of a silent mixture.
- **`commit_sha` is a strict 40-character lower-case pattern.** An abbreviated or
  upper-case SHA would not compare equal to the manifest's, and the comparison is
  the entire point of the model.
