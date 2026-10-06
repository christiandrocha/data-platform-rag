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


class IntentClassification(BaseModel):
    """Output of the intent classifier LLM call."""
    model_config = ConfigDict(frozen=True)

    intent: Intent
    collections: list[Collection] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class AnswerResult(BaseModel):
    """One product query: what the visitor saw, and what produced it (ADR-021)."""
    model_config = ConfigDict(frozen=True)

    question: str
    failed: bool
    output_class: OutputClass | None          # None only when failed
    shown_text: str                            # exactly what the page displays
    sources: list[RetrievedSource]             # rank order; shown only for "answer"
    generation: GenerationResult | None
    system_prompt_version: str
    context_format_version: str
    latency_ms: int = Field(ge=0)
    trace_id: str | None = None
    logged: bool                               # the query_log insert succeeded

    @property
    def fallback_fired(self) -> bool:          # derived, cannot disagree with the class
        return self.output_class in ("fallback", "non_compliant_refusal", "empty")


class MetricValue(BaseModel):                 # exactly one of value / error (ADR-008 D5)
    value: float | None = Field(default=None, ge=0.0, le=1.0)
    error: str | None = None


class RAGASReport(BaseModel):
    """One golden-set question's scores (ADR-008)."""
    model_config = ConfigDict(frozen=True)

    question_id: str
    intent: GoldenIntent
    trace_id: str | None
    metrics: dict[MetricName, MetricValue] | None   # None for out-of-scope
    fallback_fired: bool
    fallback_correct: bool | None                    # out-of-scope only
    pushed_to_langfuse: bool
```

The run file is an `EvalRun` (provenance + one `EvalRecord` per question: the
`GoldenQuestion`, its `AnswerResult`, its context texts). The report is an
`EvalReport` (provenance, `JudgeConfig`, the `RAGASReport`s, a `RAGASAggregate`
whose every mean carries `n_scored`/`n_expected`). `ReportComparison` is what
`compare` returns. `Origin = Literal["visitor", "eval"]` is `query_log.origin`.

## Where each model is used

| Model | Written by | Read by |
|-------|-----------|---------|
| CorpusFile / CorpusProject / CorpusManifest | scripts/fetch_corpus.py | indexer/corpus.py, scripts/index_corpus.py |
| IndexedSnapshot | indexer/writer.py | scripts/index_corpus.py (`--verify`, short-circuit) |
| IndexRunReport | scripts/index_corpus.py | the CLI's own output |
| Chunk | indexer/chunker.py | indexer/writer.py |
| ChunkMetadata | indexer/writer.py | retrieval/dense_search.py, UI |
| RetrievedChunk | retrieval/dense_search.py | generation/client.py, generation/answer.py, scripts/fallback_eval.py |
| IntentClassification | retrieval/intent_classifier.py (not built) | — |
| AnswerResult | generation/answer.py | UI, `query_log` row, Langfuse trace |
| GoldenQuestion | evaluation/golden_set_loader.py | evaluation/generate.py |
| EvalProvenance / EvalRecord / EvalRun | evaluation/generate.py | evaluation/ragas_runner.py (the run file) |
| MetricValue / RAGASReport / RAGASAggregate / JudgeConfig / EvalReport | evaluation/ragas_runner.py, evaluation/report.py | `make eval-compare`, `make eval-baseline`, Langfuse scores |
| ReportComparison | evaluation/report.py | scripts/run_evaluation.py `compare` |
| GenerationResult | generation/client.py | generation/answer.py, scripts/fallback_eval.py |
| RetrievedSource / FallbackEvalItem / FallbackRunSummary / FallbackEvalReport | scripts/fallback_eval.py | the `fallback-eval-*.json` artifact, ADR-020's Outcome |


## Generation and the fallback evaluation (ADR-020)

`generation/client.py` returns one `GenerationResult` per Claude call. The
client is injected, so these contracts are exercised on stubs and no test
calls the API. `make fallback-eval` measures rule 3 and writes one
`FallbackEvalReport`.

```python
OutputClass = Literal["fallback", "non_compliant_refusal", "empty", "answer"]
QuestionSource = Literal["golden", "out_of_scope_set"]
OutOfScopeBand = Literal["adjacent", "personal", "off_domain", "adversarial"]


class GenerationResult(BaseModel):
    text: str                 # text blocks joined in order; may be ""
    model: str                # as the API reports it
    stop_reason: str | None
    input_tokens: int
    output_tokens: int


class FallbackRunSummary(BaseModel):
    """Counts for one run. B1 = out_of_scope_fallback / out_of_scope_total,
    B2 = in_scope_false_fallback / in_scope_total. No verdict: the thresholds
    live in ADR-020 only."""
    run: int
    out_of_scope_total: int
    out_of_scope_fallback: int
    in_scope_total: int
    in_scope_false_fallback: int     # fallback + non-compliant + empty
    missed_ids: list[str]
    non_compliant_out_of_scope_ids: list[str]
    false_fallback_ids: list[str]
    empty_ids: list[str]
    non_end_turn_ids: list[str]


class FallbackEvalReport(BaseModel):
    complete: bool                   # False: not a reading, and no summaries
    incomplete_reason: str | None
    model: str                       # settings.llm_model
    temperature: float               # settings.llm_temperature
    max_tokens: int                  # settings.llm_max_tokens
    top_k: int                       # settings.rerank_top_k
    system_prompt_version: str
    system_prompt_sha256: str        # catches an edit that forgot the version bump
    context_format_version: str
    golden_set_sha256: str
    out_of_scope_set_sha256: str
    snapshots: list[IndexedSnapshot]
    summaries: list[FallbackRunSummary]
    items: list[FallbackEvalItem]    # one per question per run, with output text
    ...                              # created_at, runs_requested, token totals
```

`classify_output` (`generation/fallback.py`) checks the classes in order:
`empty`, then exact `FALLBACK_MESSAGE` (trimmed) for `fallback`, then the
LinkedIn URL for `non_compliant_refusal`, then `answer`. A refusal worded
without the URL is an `answer`, a known limitation recorded in ADR-020.

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
