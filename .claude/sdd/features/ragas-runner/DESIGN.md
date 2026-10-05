# DESIGN: The RAGAS runner

> [DEFINE.md](DEFINE.md): generate every golden-set answer through the product
> path into a run file, then score the file with RAGAS, Claude Opus 5.5 as the
> judge. Built and tested without an API key.

## Metadata

| Field | Value |
|-------|-------|
| Feature | ragas-runner |
| Depends on | [DEFINE.md](DEFINE.md) (Ready for Design, 13/15, Q1–Q5 approved 2026-10-05) |
| Status | Approved (D1–D10 approved by the author on 2026-10-05) |
| ADR needed | Yes: [ADR-008](../../../../docs/adr/ADR-008-ragas-evaluation-runner.md) (Planned). It adds a `query_log` column, a judge model and an external dependency, and it sets the regression gate's rule |

## Architecture overview

```
make eval
  1. scripts/verify_adversarials.py          (ADR-011 gate; non-zero = stop, nothing written)
  2. run_evaluation.py generate               stage 1
       golden_set_loader.load()  -> 50 GoldenQuestion
       for each: answer(question, client, origin="eval")     (ADR-021 path, unchanged)
                 contexts = chunk text by result.sources' chunk ids
       -> .claude/dev/reports/eval-run-{ts}.json             (EvalRun: provenance + 50 EvalRecord)
  3. run_evaluation.py score RUN              stage 2
       for each in-scope record: 4 RAGAS metrics (judge: Opus, embeddings: local bge)
       for each out-of-scope record: fallback_correct = result.fallback_fired
       push each score to Langfuse on record.result.trace_id
       -> .claude/dev/reports/eval-run-{ts}.report.json       (EvalReport), rewritten after each question
  4. print the aggregate table
```

**What changes:**
- `evaluation/` gets the code. The module names follow AGENTS.md's repo map,
  which already lists `ragas_runner`, `golden_set_loader` and `langfuse_scorer`.
- `answer()` gets an `origin` keyword.
- `sql/05` adds one column.
- `contracts.py`: the RAGAS models are rewritten, and the run file's models are added.
- `scripts/run_evaluation.py` replaces the stub.
- Makefile targets, `ragas.yml`, `ci.yml`, `pyproject.toml`, config.

**What stays:** retrieval, the prompt, the generation model, the output classes,
the page. The runner measures them and changes none of them.

**Modules (`data_platform_rag/evaluation/`):**

| Module | Holds |
|---|---|
| `golden_set_loader.py` | `load() -> list[GoldenQuestion]`, and the golden set's git SHA |
| `generate.py` | Stage 1: `generate_run(questions, client, connect_fn) -> EvalRun`, and the provenance header |
| `ragas_runner.py` | Stage 2: the judge and the embeddings for RAGAS, the four metrics, `score_run(run, judge, embeddings, pusher, existing) -> EvalReport`. The one module that imports `ragas`, and it does so lazily |
| `report.py` | The aggregate, the table, `compare(a, b)`, the baseline copy |
| `langfuse_scorer.py` | `ScorePusher`: one score per call, catches everything, like `tracing.py` |

## Data contracts

### `query_log.origin` (`sql/05_query_log_origin.sql`, new)

```sql
ALTER TABLE query_log ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'visitor';
COMMENT ON COLUMN query_log.origin IS 'visitor (the page) or eval (make eval stage 1). ADR-008';
```

Create-only and idempotent, as the bootstrap boundary requires. Rows that already
exist get `'visitor'`, which is true of every row a real visitor wrote. No `CHECK`
constraint: `ADD CONSTRAINT` has no `IF NOT EXISTS` in Postgres 16, and the value
comes from a `Literal` in Python.

### The run file (`contracts.py`, new)

```python
Origin = Literal["visitor", "eval"]

class GoldenQuestion(BaseModel):            # frozen
    id: str
    intent: Literal["decision", "architecture", "comparison", "out-of-scope"]
    question: str
    expected_answer: str | None             # None exactly for out-of-scope

class EvalProvenance(BaseModel):            # frozen; ADR-011 commitment 2
    created_at: datetime
    golden_set_sha: str                     # git log -1 --format=%H -- docs/golden-set/evaluation_questions.yml
    golden_set_dirty: bool                  # the file differs from that commit
    corpus_commits: list[str]               # project@sha, from corpus_snapshot
    embedding_model: str
    generation_model: str                   # settings.llm_model
    system_prompt_version: str
    context_format_version: str
    rerank_top_k: int                       # the k the answers were built from

class EvalRecord(BaseModel):                # frozen
    question: GoldenQuestion
    result: AnswerResult                    # ADR-021, unchanged
    contexts: list[str]                     # chunk text, same order as result.sources

class EvalRun(BaseModel):
    run_id: str                             # eval-run-{ts}
    provenance: EvalProvenance
    records: list[EvalRecord]
```

`rerank_top_k` is in the header because the local `.env` sets 5 and the ADRs
reason about 3 (BUILD_REPORT of streamlit-ui). A run built from 5 contexts must
say so.

### The report (`contracts.py`, `RAGASReport` and `RAGASAggregate` rewritten)

```python
MetricName = Literal["faithfulness", "answer_relevancy", "context_precision", "context_recall"]

class MetricValue(BaseModel):               # frozen; exactly one of value / error
    value: float | None = Field(default=None, ge=0.0, le=1.0)
    error: str | None = None                # "NaN from judge", "generation failed", an exception's text

class RAGASReport(BaseModel):               # one per question
    question_id: str
    intent: str
    trace_id: str | None
    metrics: dict[MetricName, MetricValue] | None   # None for out-of-scope
    fallback_fired: bool                    # also recorded in scope: a wrong fallback is a finding
    fallback_correct: bool | None           # out-of-scope only
    pushed_to_langfuse: bool

class MetricAggregate(BaseModel):
    mean: float | None                      # over scored questions only; None when none scored
    n_scored: int
    n_expected: int                         # 45

class JudgeConfig(BaseModel):
    model: str                              # settings.judge_model
    max_tokens: int
    ragas_version: str
    answer_relevancy_strictness: int

class RAGASAggregate(BaseModel):
    metrics: dict[MetricName, MetricAggregate]
    fallback_correct: int                   # of n_out_of_scope
    n_out_of_scope: int
    in_scope_fallbacks: int                 # in-scope questions that got the fallback
    n_in_scope: int

class EvalReport(BaseModel):
    run_id: str
    run_file: str
    provenance: EvalProvenance
    judge: JudgeConfig
    scored_at: datetime
    reports: list[RAGASReport]
    aggregate: RAGASAggregate
```

`dict[MetricName, ...]` keys a closed `Literal`, not `dict[str, Any]`, so the
contract rule holds.

## Interfaces

### `answer()` (ADR-021) gains one keyword

```python
def answer(question, client, *, connect_fn=None, tracer=None, origin: Origin = "visitor") -> AnswerResult
```

It is written to the row and to the trace's metadata. The page does not pass it.
Nothing else in `answer()` changes.

### `scripts/run_evaluation.py`

```
run_evaluation.py generate [--out-dir DIR]          -> prints the run file's path
run_evaluation.py score RUN_FILE [--rescore]        -> report next to RUN_FILE; resumes unless --rescore
run_evaluation.py all [--out-dir DIR]               -> generate, then score
run_evaluation.py compare REPORT_A REPORT_B         -> per-metric delta, or "not comparable" + reasons, exit 1
run_evaluation.py baseline REPORT                   -> copy to docs/eval-baselines/, refuses a non-report
```

**Preflight, before any work:** the key, the `ragas` import (score only), and the
database (generate only). Each prints one line naming what is missing and exits 2,
as `fallback_eval.py`'s `PreflightError` does.

**`compare` refuses** when any of these differ: `golden_set_sha` (ADR-011), or
`golden_set_dirty` on either side, `judge.model`, `judge.ragas_version`,
`answer_relevancy_strictness`. A difference in generation model, prompt version or
`rerank_top_k` is *allowed*, because that is what a comparison is for. The output
prints those differences on top of the deltas.

### Makefile

| Target | Runs |
|---|---|
| `eval` | `verify-adversarials`, then `run_evaluation.py all` |
| `eval-ci` | the same, with `--out-dir .claude/dev/reports` |
| `eval-score run=FILE` | `score FILE` (rescoring or resuming without new answers) |
| `eval-compare a=X b=Y` | `compare X Y` |
| `eval-baseline run=REPORT` | `baseline REPORT` |

`make eval` already writes to `.claude/dev/reports` (the stub's `eval-ci` did). It
keeps that directory, because stage 2 needs a file to read.

### Config (`config.py`, `.env.example`)

```python
judge_model: str = "claude-opus-5-5"         # DEFINE Q2
judge_max_tokens: int = Field(default=4096, gt=0)
answer_relevancy_strictness: int = Field(default=3, ge=1)   # RAGAS's default
```

`judge_max_tokens = 4096` is not measured. RAGAS's default is 1024, and its own
docstring warns that structured output truncates below "4096+". A truncated reply
fails validation, and D7 records it as a missing value with the reason, never a
score. The first real run shows whether 4096 truncates anything.

### Telemetry

`ragas_runner.py` sets `os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")`
before its lazy `import ragas`. That is the one place the variable is written.
`setdefault` lets a person opt back in, explicitly. AGENTS.md's "no `os.getenv` in
application code" is about reading config. This is a write that guards a third
party's default, and ADR-008 records it.

## Retrieval and RAG-specific concerns

- [x] **Chunking:** not affected.
- [x] **HNSW / index:** not affected. Stage 1 reads `chunks.content` by id. That
      is a primary-key lookup, not a retrieval query, so `sql/99_verify.sql` is
      unchanged.
- [x] **Query pattern:** the product query is unchanged. The contexts are fetched
      in the same stage-1 loop, right after `answer()`. Chunk ids are stable until
      the next reindex, and the header records the corpus commits.
- [x] **RAGAS metrics:** this feature *creates* them. **Regression risk: none.**
      Retrieval, the prompt, the model and the context format are unchanged. The
      `origin` keyword only writes a column.

## Decisions for the author (D1–D10)

- [x] **D1. One PR, not two.** Stage 1 alone produces nothing to look at, and
      stage 2 cannot be tested on real data until stage 1 exists. Estimated size
      is close to streamlit-ui's PR 1.
- [x] **D2. The contexts are fetched by chunk id after `answer()`**, instead of
      adding the text to `AnswerResult`. The product contract would otherwise carry
      text the page never shows.
- [x] **D3. Real RAGAS in the tests, with a fake judge.** RAGAS 0.4.3's judge
      interface is `agenerate(prompt, response_model) -> response_model`. A fake
      that returns prepared instances per response model runs **RAGAS's own
      metric code** offline. This tests the wiring, not just our side of it.
- [x] **D4. `ci.yml`'s test job installs `.[dev,eval]`.** Otherwise the RAGAS
      tests would skip in CI. A skip passes silently, which is the PR #35 lesson
      in another form. Cost: a heavier install (`langchain`, `openai`,
      `instructor` and others arrive with `ragas`). Their size is not measured.
- [x] **D5. The judge uses `anthropic.AsyncAnthropic`.** RAGAS's metrics call
      `agenerate`, which raises `TypeError` on a sync client (read in
      `ragas/llms/base.py`). `generation/sdk.py` gains `build_async_client()`, and
      stays the one place that imports the SDK.
- [x] **D6. The embeddings are an adapter over `embed_query`**, the same cached
      `bge-small-en-v1.5` instance retrieval uses, rather than RAGAS's Hugging
      Face provider loading the model a second time. Answer relevancy compares
      questions to questions, so the query-side embedding is the right one for
      both.
- [x] **D7. Missing, never zero.** A metric that raises, returns NaN, or belongs
      to a question whose generation failed is a `MetricValue` with `error` set.
      Means are computed over scored questions only, and always printed as
      `mean (n/45)`.
- [x] **D8. In-scope questions that got the fallback are scored as they are**
      (low faithfulness and relevancy are the true result), and also counted in
      `in_scope_fallbacks`. Excluding them would hide a product failure from the
      score.
- [x] **D9. The regression rule: form now, number later, and how the number is
      chosen is fixed now** (AGENTS.md: "a decision rule fixed in its ADR before
      measuring"). **A correction to DEFINE Q4:** scoring one run file twice
      measures only the *judge's* noise. A regression check compares two
      *generations*, and the answers themselves vary between runs. The proposal:
      - Generate **2** runs, and score each **twice**. That gives judge noise
        (same answers, two scorings) and total noise (two runs).
      - The threshold per metric is **the larger of the observed differences**.
        A drop beyond it fails `compare --gate`.
      - Until the threshold exists, `compare` reports and never fails on a delta.

      This doubles the first real run's generation. Its cost is not known before
      it runs.
- [x] **D10. The baseline path is `docs/eval-baselines/{run_id}.report.json`**,
      committed, with its run file next to it. A report without the answers it
      judged cannot be audited.

## Alternatives considered

- **Add `contexts: list[str]` to `AnswerResult`.** Simplest for stage 1. Rejected
  (D2): the product contract would carry evaluation data, and the page would hold
  chunk text in memory that it never displays.
- **Stage 1 bypasses `answer()`** and calls retrieval and generation directly, as
  `fallback_eval.py` does. No `query_log` rows at all. Rejected in BRAINSTORM: no
  product trace, so no score can attach to one (AGENTS.md).
- **RAGAS's `evaluate()` over a `datasets.Dataset`.** The 0.2-era batch API.
  Rejected: it returns a table where a failed sample is a NaN, which D7 then has
  to reverse-engineer. Calling each metric's `ascore` gives the exception itself.
- **Score concurrently.** Faster. Deferred: rate limits on a new key are unknown,
  and one question at a time keeps the resumable report simple. It can be added
  once a real run shows the time.
- **Mock RAGAS entirely in tests** (a fake scorer instead of a fake judge). Rejected
  (D3): the RAGAS wiring (prompt models, async calls, NaN cases) would only meet
  reality on the first paid run.

## Test plan

**No test calls an API, needs a key, or needs network.**

**Unit:**
- `golden_set_loader`: 50 questions, 45 with `expected_answer`, 5 out of scope
  without one. The SHA matches `git log`. A modified file sets `golden_set_dirty`.
- `generate_run` with a stub client, a recording connection, and fixture chunk
  text: 50 records, contexts in `sources` order, `origin="eval"` passed through,
  and a failed `answer()` recorded with the run continuing.
- `ragas_runner` with the **fake judge** (D3) and a fake embedding:
  - each metric gives a value computed by RAGAS's own code;
  - a judge that raises on one metric of one question gives one `error` and no 0;
  - a NaN becomes an `error`;
  - an out-of-scope record gives `fallback_correct` only;
  - an in-scope fallback is scored and counted (D8);
  - resume skips scored records, and `--rescore` does not.
- `RAGAS_DO_NOT_TRACK` is `"true"` after `ragas_runner` loads RAGAS. An explicit
  `false` is kept.
- `report`:
  - means over scored questions only, with the `n/45` coverage;
  - `compare` refuses on each refusing field and prints the reason;
  - `compare` allows a prompt or model change and prints it;
  - `baseline` refuses a JSON that is not an `EvalReport`.
- `langfuse_scorer`:
  - with a recording fake: 4 scores per in-scope record and 1 per out-of-scope
    record, on the right trace id;
  - with a client that raises: same report, `pushed_to_langfuse=False`;
  - a record with no trace id is not pushed.
- `run_evaluation.py`: no key exits 2 with 0 calls, for every subcommand that
  calls an API.
- Contracts: `MetricValue` with both or neither of value and error fails.

**Integration (local Postgres):**
- Stage 1 against the `_test` database, with a stub client and hand-placed chunks:
  every row has `origin = 'eval'`, and a page-path row has `'visitor'`.
- `sql/05` applied twice on a populated `query_log`: no error, existing rows
  read `'visitor'`.
- The contexts in the run file equal `chunks.content` for the retrieved ids.

**Manual, without a key:**
- `make eval` with a planted contamination failure stops before generating.
- `make eval` with no key prints one line and exits non-zero.
- `make bootstrap` twice.

**Manual, with the key (later):** D9's measurement, two runs scored twice each,
recorded in ADR-008. Read 3 in-scope traces in Langfuse and check their scores.

## Rollout plan

**One PR (D1).** BUILD order:
1. ADR-008 (Planned) and its index row are committed with this DESIGN.
2. `pip install -e ".[dev,eval]"` with the new pins; read the installed RAGAS for
   the four metrics' prompt models (the fake judge needs them).
3. `sql/05`, `make bootstrap`, the `origin` keyword, and the integration conftest
   built with `sql/05`.
4. Contracts, config, `golden_set_loader`, `generate`, `langfuse_scorer`,
   `ragas_runner`, `report`, the script, the Makefile, and tests alongside each.
5. `ci.yml` (D4), and `ragas.yml`: `sql/04` and `05`, and
   `run_evaluation.py all`. It stays `workflow_dispatch`.
6. Mirrors:
   - AGENTS.md: the repo map, `sql/00`–`05`, the Makefile target count, and the
     eval commands.
   - KB: `evaluation/ragas-metrics.md` (the 0.05 rule replaced by D9) and
     `pydantic/models.md`.
   - README: roadmap item 7.
   - ADR-011: an in-place note that ADR-008 now exists and meets its two
     preconditions.

**Migration:** `sql/05` runs in `make bootstrap` after `04`. No backfill: the
default fills existing rows.

**No feature flag.** Nothing runs without a key, and nothing runs on a push.

**Rollback:** revert the PR. The `origin` column stays in any database that ran
`sql/05`. It has a default, so the old `answer()` ignores it. Removing it is
`make reset-db`.

## Open questions

D1–D10 above. Also, outside this feature: **ADR-021 still reads "Planned —
Accepted when BUILD lands"**, and its BUILD landed in #35 and #36. Changing its
status is the author's call. It is noted here and not edited.
