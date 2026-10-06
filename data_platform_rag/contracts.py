"""Pydantic v2 contracts for all inter-module boundaries in data-platform-rag.

Per ADR-010, this is the single source of truth for data crossing module
boundaries. No dict[str, Any] in public APIs. Every new boundary starts here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, model_validator

# ─── Type aliases ────────────────────────────────────────────────────────────

Collection = Literal["decisions", "architecture"]
SourceProject = Literal["sdd-kafka-snowflake-2", "sdd-kafka-databricks"]
SourceType = Literal["adr", "readme", "contract", "macro", "schema"]
Intent = Literal["decision", "architecture", "comparison", "hybrid"]
ADRStatus = Literal["accepted", "superseded", "resolved", "planned"]

# Fallback evaluation (ADR-020). `empty` is DEFINE Amendment 1's fourth class.
OutputClass = Literal["fallback", "non_compliant_refusal", "empty", "answer"]
# Who asked (ADR-008): the page, or `make eval` stage 1. Written to query_log.origin.
Origin = Literal["visitor", "eval"]
QuestionSource = Literal["golden", "out_of_scope_set"]
OutOfScopeBand = Literal["adjacent", "personal", "off_domain", "adversarial"]


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
    """A chunk returned by dense retrieval (ADR-018), before reranking.

    Five fields, all produced by the query. `rrf_score`, `sparse_score` and
    `sparse_rank` were removed in ADR-019 Amendment 1: since ADR-018 they held the
    rank as a float, 0.0 and None for every chunk. `extra="forbid"` makes a caller
    still passing one fail loudly instead of having it silently dropped.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    content: str
    metadata: ChunkMetadata
    dense_distance: float = Field(ge=0.0)
    # Required since dense-only retrieval: every returned chunk has a dense rank.
    dense_rank: int = Field(ge=1)


# ─── Intent classification ───────────────────────────────────────────────────


class IntentClassification(BaseModel):
    """Output of the intent classifier LLM call."""

    model_config = ConfigDict(frozen=True)

    intent: Intent
    collections: list[Collection] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


# ─── Generation ──────────────────────────────────────────────────────────────


class GenerationResult(BaseModel):
    """One Claude call: what came back, and what it cost."""

    model_config = ConfigDict(frozen=True)

    # Every text block of the response, joined in order. May be "": an empty
    # output is a class of its own (ADR-020), not an error.
    text: str
    model: str  # as the API reports it, not as requested
    stop_reason: str | None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


# ─── Fallback evaluation (ADR-020) ───────────────────────────────────────────


class RetrievedSource(BaseModel):
    """What a question's context was built from. Citation fields only, no text."""

    model_config = ConfigDict(frozen=True)

    chunk_id: int
    source_project: SourceProject
    source_path: str
    source_anchor: str | None
    adr_id: str | None
    dense_distance: float = Field(ge=0.0)

    @classmethod
    def from_chunk(cls, chunk: RetrievedChunk) -> RetrievedSource:
        """The citation fields of one retrieved chunk. Shared by ADR-020 and ADR-021."""
        meta = chunk.metadata
        return cls(
            chunk_id=chunk.id,
            source_project=meta.source_project,
            source_path=meta.source_path,
            source_anchor=meta.source_anchor,
            adr_id=meta.adr_id,
            dense_distance=chunk.dense_distance,
        )


class FallbackEvalItem(BaseModel):
    """One question in one run of `make fallback-eval`."""

    model_config = ConfigDict(frozen=True)

    run: int = Field(ge=1)
    question_id: str
    source: QuestionSource
    intent: str  # the golden-set intent, verbatim
    band: OutOfScopeBand | None  # every out-of-scope question; None in-scope
    expects_fallback: bool
    retrieved: list[RetrievedSource]
    output_text: str
    output_class: OutputClass
    stop_reason: str | None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class FallbackRunSummary(BaseModel):
    """The two numbers ADR-020's rule reads, for one run. Counts, not a verdict.

    B1 is `out_of_scope_fallback / out_of_scope_total`, B2 is
    `in_scope_false_fallback / in_scope_total`. The thresholds live in the ADR
    and nowhere in code, so code cannot drift from them.
    """

    model_config = ConfigDict(frozen=True)

    run: int = Field(ge=1)
    out_of_scope_total: int = Field(ge=0)
    out_of_scope_fallback: int = Field(ge=0)
    in_scope_total: int = Field(ge=0)
    in_scope_false_fallback: int = Field(ge=0)  # fallback + non-compliant + empty
    missed_ids: list[str]  # out-of-scope, any class but fallback
    non_compliant_out_of_scope_ids: list[str]
    false_fallback_ids: list[str]  # in-scope, fallback, non-compliant or empty
    empty_ids: list[str]  # either side
    non_end_turn_ids: list[str]  # any stop_reason other than end_turn


class FallbackEvalReport(BaseModel):
    """The artifact of `make fallback-eval`: everything needed to re-read it later.

    `complete=False` is not a reading (ADR-020): a call failed or the run was
    interrupted. It carries the outputs it has and no summaries, so there is no
    number to look at before starting over.
    """

    model_config = ConfigDict(frozen=True)

    created_at: datetime
    complete: bool
    incomplete_reason: str | None
    model: str
    temperature: float
    max_tokens: int
    runs_requested: int = Field(ge=1)
    top_k: int = Field(ge=1)
    system_prompt_version: str
    system_prompt_sha256: str
    context_format_version: str
    golden_set_sha256: str
    out_of_scope_set_sha256: str
    snapshots: list[IndexedSnapshot]
    summaries: list[FallbackRunSummary]
    items: list[FallbackEvalItem]
    total_input_tokens: int = Field(ge=0)
    total_output_tokens: int = Field(ge=0)


# ─── Product query path (ADR-021) ────────────────────────────────────────────


class AnswerResult(BaseModel):
    """One product query: what the visitor saw, and what produced it.

    Replaces the pre-ADR-018 shape (`intent`, reranked chunks, `top_score`),
    which described stages that do not run and had no importer.
    """

    model_config = ConfigDict(frozen=True)

    question: str
    failed: bool
    output_class: OutputClass | None  # None only when failed
    shown_text: str  # exactly what the page displays
    sources: list[RetrievedSource]  # rank order; the page shows them only for "answer"
    generation: GenerationResult | None  # None when the query failed before a response
    system_prompt_version: str
    context_format_version: str
    latency_ms: int = Field(ge=0)
    trace_id: str | None = None
    logged: bool  # the query_log insert succeeded

    @property
    def fallback_fired(self) -> bool:
        """The visitor got no answer: ADR-020's B2 grouping. A failure is not a fallback.

        A property, not a field, so it cannot disagree with `output_class`.
        """
        return self.output_class in ("fallback", "non_compliant_refusal", "empty")


# ─── RAGAS evaluation (ADR-008) ──────────────────────────────────────────────
#
# Stage 1 (`make eval` generate) writes an `EvalRun`; stage 2 (score) reads it and
# writes an `EvalReport`. The models before ADR-008 required four scores for every
# question, which the out-of-scope questions cannot have (no reference answer).

GoldenIntent = Literal["decision", "architecture", "comparison", "out-of-scope"]
MetricName = Literal["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
METRIC_NAMES: tuple[MetricName, ...] = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
)


class GoldenQuestion(BaseModel):
    """One `evaluation_questions.yml` entry, the fields a run uses."""

    model_config = ConfigDict(frozen=True)

    id: str
    intent: GoldenIntent
    question: str
    expected_answer: str | None  # None exactly for out-of-scope

    @property
    def in_scope(self) -> bool:
        return self.intent != "out-of-scope"

    @model_validator(mode="after")
    def _reference_matches_scope(self) -> GoldenQuestion:
        if self.in_scope != bool(self.expected_answer):
            raise ValueError(
                f"{self.id}: an in-scope question needs an expected_answer, "
                "and an out-of-scope one has none"
            )
        return self


class EvalProvenance(BaseModel):
    """What a run was made from. ADR-011 commitment 2, plus what ADR-008 compares."""

    model_config = ConfigDict(frozen=True)

    created_at: datetime
    golden_set_sha: str  # last commit of evaluation_questions.yml
    golden_set_dirty: bool  # the file differs from that commit
    corpus_commits: list[str]  # project@sha
    embedding_model: str
    generation_model: str
    system_prompt_version: str
    context_format_version: str
    rerank_top_k: int = Field(gt=0)


class EvalRecord(BaseModel):
    """One question's answer, and the text it was built from."""

    model_config = ConfigDict(frozen=True)

    question: GoldenQuestion
    result: AnswerResult
    contexts: list[str]  # chunk text, in `result.sources` order

    @model_validator(mode="after")
    def _one_context_per_source(self) -> EvalRecord:
        if len(self.contexts) != len(self.result.sources):
            raise ValueError(
                f"{self.question.id}: {len(self.contexts)} contexts "
                f"for {len(self.result.sources)} sources"
            )
        return self


class EvalRun(BaseModel):
    """What stage 1 writes: a run file."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    provenance: EvalProvenance
    records: list[EvalRecord]


class MetricValue(BaseModel):
    """A score, or the reason there is none. Never both, never neither (ADR-008 D5)."""

    model_config = ConfigDict(frozen=True)

    value: float | None = Field(default=None, ge=0.0, le=1.0)
    error: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> MetricValue:
        if (self.value is None) == (self.error is None):
            raise ValueError("a MetricValue holds exactly one of value and error")
        return self


class RAGASReport(BaseModel):
    """One question's scores."""

    model_config = ConfigDict(frozen=True)

    question_id: str
    intent: GoldenIntent
    trace_id: str | None
    metrics: dict[MetricName, MetricValue] | None  # None for out-of-scope
    fallback_fired: bool  # recorded in scope too: a wrong fallback is a finding
    fallback_correct: bool | None  # out-of-scope only
    pushed_to_langfuse: bool


class MetricAggregate(BaseModel):
    """A mean over the questions that have a score, and how many that is."""

    model_config = ConfigDict(frozen=True)

    mean: float | None = Field(default=None, ge=0.0, le=1.0)  # None when nothing scored
    n_scored: int = Field(ge=0)
    n_expected: int = Field(ge=0)


class JudgeConfig(BaseModel):
    """What scored a run. Two reports with different judges are not comparable."""

    model_config = ConfigDict(frozen=True)

    model: str
    max_tokens: int = Field(gt=0)
    temperature: float = Field(ge=0.0, le=1.0)
    ragas_version: str
    answer_relevancy_strictness: int = Field(ge=1)


class RAGASAggregate(BaseModel):
    """The run's numbers. Every mean carries its coverage."""

    model_config = ConfigDict(frozen=True)

    metrics: dict[MetricName, MetricAggregate]
    fallback_correct: int = Field(ge=0)
    n_out_of_scope: int = Field(ge=0)
    in_scope_fallbacks: int = Field(ge=0)  # in-scope questions that got the fallback
    n_in_scope: int = Field(ge=0)


class EvalReport(BaseModel):
    """What stage 2 writes, next to the run file it scored."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    run_file: str
    provenance: EvalProvenance
    judge: JudgeConfig
    scored_at: datetime
    reports: list[RAGASReport]
    aggregate: RAGASAggregate


class ReportComparison(BaseModel):
    """`compare(a, b)`: B's means minus A's, or why the two cannot be compared."""

    model_config = ConfigDict(frozen=True)

    comparable: bool
    refusals: list[str]  # why not comparable; empty when comparable
    differences: list[str]  # what differs in what was evaluated (model, prompt, k)
    deltas: dict[MetricName, float | None]  # None when either side has no mean
