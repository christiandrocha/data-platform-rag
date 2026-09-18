"""Pydantic v2 contracts for all inter-module boundaries in data-platform-rag.

Per ADR-010, this is the single source of truth for data crossing module
boundaries. No dict[str, Any] in public APIs. Every new boundary starts here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AnyUrl, BaseModel, ConfigDict, Field

# ─── Type aliases ────────────────────────────────────────────────────────────

Collection = Literal["decisions", "architecture"]
SourceProject = Literal["sdd-kafka-snowflake-2", "sdd-kafka-databricks"]
SourceType = Literal["adr", "readme", "contract", "macro", "schema"]
Intent = Literal["decision", "architecture", "comparison", "hybrid"]
ADRStatus = Literal["accepted", "superseded", "resolved", "planned"]


# ─── Corpus snapshot manifest (written at acquisition time) ──────────────────
#
# Per ADR-012. The manifest is what makes a score reproducible: it names the
# exact commit and file bytes a run was measured against. Without it, an eval
# can index commit X while the adversarial gate greps commit Y and nothing
# compares them.


class CorpusFile(BaseModel):
    """One extracted in-corpus file, as it exists in the snapshot."""

    model_config = ConfigDict(frozen=True)

    path: str  # relative to the project directory inside the snapshot
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_type: SourceType


class CorpusProject(BaseModel):
    """One corpus repo at one commit, and the files extracted from it."""

    model_config = ConfigDict(frozen=True)

    project: SourceProject
    # AnyUrl, not HttpUrl: the two corpora are https, but a file:// URL is a
    # valid clone source, and requiring https would make acquisition testable
    # only with network access.
    repo_url: AnyUrl
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    files: list[CorpusFile] = Field(min_length=1)


class CorpusManifest(BaseModel):
    """MANIFEST.json at the snapshot root. The provenance record of one fetch."""

    model_config = ConfigDict(frozen=True)

    # Present from v1 because slice 2 must store these SHAs beside the indexed
    # rows, and a format that cannot be versioned cannot be migrated.
    schema_version: int = 1
    created_at: datetime
    projects: list[CorpusProject] = Field(min_length=1)


# ─── Indexed corpus provenance (written at index time) ───────────────────────
#
# Per ADR-013. `CorpusManifest` above is the on-disk record of a fetch; these are
# the database's record of what was actually indexed from it. The pair is what
# makes `indexed corpus == verified corpus` an executable comparison rather than
# a promise.


class IndexedSnapshot(BaseModel):
    """One project's provenance row, as written to `corpus_snapshot`."""

    model_config = ConfigDict(frozen=True)

    source_project: SourceProject
    repo_url: AnyUrl
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    file_count: int = Field(gt=0)
    manifest_created_at: datetime
    manifest_schema_version: int = Field(ge=1)
    # Which embedding space the vectors live in. A VECTOR(384) column accepts
    # vectors from any 384-dimensional model, so the model name is the only thing
    # that distinguishes a healthy index from two embedding spaces mixed together.
    embedding_model: str = Field(min_length=1)
    embedding_dim: int = Field(gt=0)
    chunk_count: int = Field(ge=0)

    def is_current_for(self, commit_sha: str, embedding_model: str) -> bool:
        """Whether a re-index would be a no-op: same commit, same model.

        The short-circuit key. Deliberately includes the model, so that changing
        `settings.embedding_model` forces a re-embed instead of leaving half the
        corpus in the old embedding space.
        """
        return self.commit_sha == commit_sha and self.embedding_model == embedding_model


class IndexRunReport(BaseModel):
    """What one `make index-corpus` invocation did. The CLI's return value.

    Also what `--verify` returns, with `written` empty: verification asks the same
    question indexing answers, so it reports in the same shape.
    """

    model_config = ConfigDict(frozen=True)

    snapshot_root: str
    written: list[IndexedSnapshot] = Field(default_factory=list)
    skipped: list[SourceProject] = Field(default_factory=list)
    embedding_model: str
    duration_seconds: float = Field(ge=0.0)

    @property
    def chunks_written(self) -> int:
        return sum(snapshot.chunk_count for snapshot in self.written)


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
    # Noun phrases extracted at index time (regex + stop-word filter, no NER).
    # Unused by v1 retrieval; enables a `WHERE keywords && ARRAY[...]` pre-filter
    # later without a contract change. None = not extracted; [] = extracted, empty.
    keywords: list[str] | None = None
    chunk_index: int = Field(ge=0)
    token_count: int = Field(gt=0)


class Chunk(BaseModel):
    """A chunk ready for embedding and storage: its text plus its metadata.

    Replaces the `Chunk` dataclass that lived in `indexer/chunker.py` and had
    drifted from `ChunkMetadata` — flat where this is nested, `str` where this is
    `Literal`, and missing `keywords` entirely (dev-log #1). One shape now, and
    it matches `RetrievedChunk`, so the same fields survive the round trip from
    index time to retrieval time.
    """

    model_config = ConfigDict(frozen=True)

    content: str = Field(min_length=1)
    collection: Collection
    metadata: ChunkMetadata


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
