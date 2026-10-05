# DESIGN: The product query path, and the page a visitor asks on

> [DEFINE.md](DEFINE.md). How `answer()`, its `query_log` row, its trace and the
> page are built, all testable on a stub client without an API key.

## Metadata

| Field | Value |
|-------|-------|
| Feature | streamlit-ui |
| Depends on | [DEFINE.md](DEFINE.md), Ready for Design (Q1–Q6 approved 2026-10-05) |
| Status | Approved (D1–D8 approved by the author on 2026-10-05) |
| ADR needed | Yes: [ADR-021](../../../../docs/adr/ADR-021-product-query-path.md), Status Planned until BUILD |

## Facts checked before designing

- **A reindex deletes the project's `corpus_snapshot` row** (`writer.py`,
  `DELETE FROM corpus_snapshot WHERE source_project = %s`; the cascade clears its
  chunks), and the new row gets a new `BIGSERIAL` id. So a `snapshot_ids` column
  dangles after a reindex exactly as `retrieved_ids` does. DEFINE Q1 proposed
  `snapshot_ids`. **This design records `corpus_commits` instead** (D2), the
  `project@sha` pairs, which survive any reindex.
- **The longest questions:** golden set 195 characters (q024), out-of-scope set
  216 (oos025, the forged chunk). Q6's cap must clear 216.
- **`make deploy` is `git push origin main`.** No `deploy.yml` exists. If a
  Streamlit Cloud app already tracks `main`, merging this feature publishes the
  page whatever `make deploy` checks (D7).
- **`langfuse`, `streamlit` and `anthropic` are declared in `pyproject.toml` but
  not installed in `.venv`.** BUILD starts with `pip install -e .`. That needs no
  key and makes no call.
- **The Langfuse 2.x surface used here** (`trace`, `trace.span`,
  `trace.generation`, `trace.update`, `trace.id`, `flush`) is checked against the
  installed 2.x source in BUILD, not from memory. The KB's
  `traces-and-generations.md` already draws this trace shape.

## Architecture overview

```text
ui/app.py (Streamlit)
  ├─ settings; key empty?  → "generation is not configured". Nothing runs (Q4)
  ├─ len(question) > settings.max_question_chars → "too long". Nothing runs (Q6)
  └─ answer(question, client=cached SDK client)
        │
generation/answer.py :: answer(question, client, *, connect_fn, tracer)
  1. trace = tracer.start(question)                       never raises
  2. with connect(): chunks = retrieve(question, top_k=rerank_top_k, conn)
                                                          span "dense_retrieval"
  3. result = generate(question, chunks, client)          generation "anthropic_call"
  4. output_class = classify_output(result.text)
  5. shown = per-class display (DEFINE table)
  6. insert one query_log row (same connection)           failure logged, not raised
  7. trace.finish(...)                                    never raises
  → AnswerResult

Any exception in 2–3 → failed=True, shown = FAILED_MESSAGE, row still attempted.
```

**What changes:** `contracts.py` (`AnswerResult` rewritten, `RerankedChunk`
removed), new `generation/answer.py`, new `observability/tracing.py`, new
`generation/sdk.py`, `sql/04_query_log_product.sql`, `ui/app.py`, `config.py`
(one setting), `Makefile` (`bootstrap`, `deploy`), `scripts/check_deploy_gate.py`.
**What stays:** retrieval, `prompt.py`, `client.generate()`,
`fallback.classify_output()`, `fallback_eval.py` (except that its `make_client`
delegates to `generation/sdk.py`).

## Data contracts

### `query_log`: `sql/04_query_log_product.sql` (new, create-only)

Added to `make bootstrap` after `03`. Every statement is `ADD COLUMN IF NOT
EXISTS` or `COMMENT ON`, so a second bootstrap on a populated database is a
no-op. No `DROP`.

```sql
ALTER TABLE query_log
    ADD COLUMN IF NOT EXISTS output_class TEXT
        CHECK (output_class IN ('fallback', 'non_compliant_refusal', 'empty', 'answer')),
    ADD COLUMN IF NOT EXISTS failed BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS error TEXT,                  -- exception class: message, ≤ 500 chars
    ADD COLUMN IF NOT EXISTS model TEXT,                  -- as the API reports it
    ADD COLUMN IF NOT EXISTS system_prompt_version TEXT,
    ADD COLUMN IF NOT EXISTS context_format_version TEXT,
    ADD COLUMN IF NOT EXISTS input_tokens INT,
    ADD COLUMN IF NOT EXISTS output_tokens INT,
    ADD COLUMN IF NOT EXISTS stop_reason TEXT,
    ADD COLUMN IF NOT EXISTS corpus_commits TEXT[],       -- 'project@sha', from the retrieved chunks
    ADD COLUMN IF NOT EXISTS embedding_model TEXT,
    ADD COLUMN IF NOT EXISTS trace_id TEXT;               -- Langfuse trace, NULL on the no-op client
```

`COMMENT ON COLUMN` for: `intent` and `reranker_top_score` (always NULL since
ADR-018 and ADR-005; kept because the bootstrap path never drops),
`retrieved_scores` (holds cosine **distances** since ADR-018, lower is closer),
`fallback_fired` (true for `fallback`, `non_compliant_refusal` and `empty`: the
visitor got no answer, ADR-020's B2 grouping), `answer_length` (characters shown,
0 unless the class is `answer`).

`corpus_commits` and `embedding_model` are filled **in the insert itself**, from
the chunks retrieved, so they say what actually answered and cost no extra round
trip:

```sql
INSERT INTO query_log (..., corpus_commits, embedding_model)
SELECT ..., array_agg(DISTINCT s.source_project || '@' || s.commit_sha ORDER BY 1),
       min(s.embedding_model)
FROM chunks c JOIN corpus_snapshot s ON s.id = c.snapshot_id
WHERE c.id = ANY(%(retrieved_ids)s)
```

A failed query with no chunks inserts with a plain `VALUES`, both columns NULL.

### `AnswerResult` (rewritten in `contracts.py`)

```python
class AnswerResult(BaseModel):
    """One product query: what the visitor saw, and what produced it."""
    model_config = ConfigDict(frozen=True)

    question: str
    failed: bool
    output_class: OutputClass | None          # None only when failed
    shown_text: str                            # what the page displays
    sources: list[RetrievedSource]             # rank order; the page shows them only for "answer"
    generation: GenerationResult | None        # None when failed before or during the call
    system_prompt_version: str
    context_format_version: str
    latency_ms: int = Field(ge=0)
    trace_id: str | None = None
    logged: bool                               # the query_log insert succeeded
```

`RetrievedSource` and `GenerationResult` are reused from ADR-020. `fallback_fired`
is a property, not a field, so it cannot disagree with `output_class`.
`RerankedChunk` is deleted: nothing imports it and ADR-005 rejected the reranker.
The old `AnswerResult` had no importer either (checked with `grep`).

## Interfaces

### `generation/answer.py`

```python
FAILED_MESSAGE = "Sorry, I could not answer right now. Please try again in a moment."

def answer(
    question: str,
    client: LLMClient,
    *,
    connect_fn: Callable[[], psycopg.Connection] | None = None,   # default: writer.connect(settings.database_url)
    tracer: QueryTracer | None = None,                            # default: tracing.get_tracer()
) -> AnswerResult:
```

- Raises only `ValueError` for an empty question or one over
  `settings.max_question_chars`. Those are caller errors, rejected before
  anything runs, and they write no row: no query ran (D5).
- Every other failure becomes `failed=True`. `KeyboardInterrupt` and
  `SystemExit` are not caught.
- The display per class is a pure function, `shown_text_for(output_class,
  text)`, unit-tested on its own.

### `observability/tracing.py`

A thin wrapper over `get_client()`. `QueryTracer.start(question) -> QueryTrace`.
`QueryTrace` has `retrieval(...)`, `generation(...)`, `finish(...)` and `id`.
**Every method catches `Exception`, logs one warning, and returns.** That is the
whole of "never block on Langfuse", in one place. On the no-op client, `id` is
None. The trace shape is the KB's:

| entity | name | holds |
|---|---|---|
| trace | `query` | input question, output shown text, metadata: output class, fallback_fired, failed, prompt and context versions, latency |
| span | `dense_retrieval` | input question and top_k, output `[chunk_id, dense_distance]` |
| generation | `anthropic_call` | model, the user message, output text, usage input/output tokens, stop reason |

### `generation/sdk.py`

`build_client(api_key: str) -> LLMClient`. The one place outside tests that
imports `anthropic`, lazily. `fallback_eval.make_client` delegates to it and keeps
its `PreflightError` wrapping.

### `ui/app.py`

- `st.cache_resource` holds the SDK client. The embedder is already an
  `lru_cache` singleton. A connection is opened per query (`connect_fn`), so a
  dropped connection never poisons the session.
- A form: one text area with `max_chars=settings.max_question_chars`, a submit
  button.
- Answer: `shown_text` as Markdown, then a "Sources" list, one line per source:
  project, path, ADR id when present, section when present, deduplicated in rank
  order.
- Fallback, non-compliant refusal, empty, failed: `shown_text`, nothing else.
- One caption: "Questions are logged to improve the answers." (DEFINE SHOULD).
- No key: `st.info("Generation is not configured: ANTHROPIC_API_KEY is empty.")`
  and the form is not drawn.

### Config

`max_question_chars: int = Field(default=500, ge=216)` (D4). The `ge` makes a
cap below the longest evaluated question a startup error.

### `make deploy`

```make
deploy:
	$(PY) scripts/check_deploy_gate.py
	git push origin main
```

`check_deploy_gate.py` reads ADR-020's `**Status**:` line and exits 1 unless it
starts with `Accepted`. The function takes the file path, so the test runs on
`tmp_path` files.

## Retrieval and RAG-specific concerns

- [x] **Chunking:** untouched.
- [x] **HNSW:** untouched. No reindex.
- [x] **Query pattern:** the retrieval query is unchanged. One new statement, the
      `query_log` insert with its join on `chunks.id = ANY(...)`, uses the primary
      key. It is not a top query pattern, so `sql/99_verify.sql` is unchanged.
- [x] **RAGAS:** no regression risk. Retrieval, prompt, model and context format
      are ADR-020's, unchanged. This feature makes the trace RAGAS scores attach
      to.

## Alternatives considered

- **Return the old `AnswerResult` filled with placeholders.** `intent`,
  `RerankedChunk` and `top_score` would hold invented values. A contract that
  lies is worse than a rewrite with no importers.
- **`snapshot_ids` in `query_log`** (DEFINE Q1's draft). They dangle after a
  reindex. `corpus_commits` does not.
- **Wrap each Langfuse call site in `try/except` inside `answer()`.** Four copies
  of the same guard, and one missed copy breaks the "never block" rule. One
  wrapper module holds it once.
- **A long-lived connection in `st.cache_resource`.** Saves a few milliseconds,
  and a dropped connection then fails every later query in the session. Not
  worth it at this traffic.
- **Fill the new columns from `settings` instead of the chunks.** Settings say
  what *should* be indexed. The join says what answered.

## Test plan

No test calls the API, needs a key, or needs network.

**Unit (no database):**
- `shown_text_for`: the four classes, per DEFINE's table.
- `AnswerResult.fallback_fired` for each class and for failed.
- `QueryTrace` over a fake client that raises on every method: each method
  returns, one warning logged per call. Over the no-op client: `id` is None.
- `check_deploy_gate`: `Accepted …` passes; `Planned …`, `Rejected …`, a missing
  Status line and a missing file fail.
- `answer()` rejects an empty question and one of `max_question_chars + 1`
  characters with `ValueError`, before `connect_fn` is called.
- `max_question_chars` below 216 fails settings validation.

**Integration (local Postgres, stub client, recording fake tracer):**
- The four classes and two failures (the stub raises; retrieval raises): **1**
  row each, its columns matching the `AnswerResult`; `corpus_commits` holds the
  `project@sha` of the retrieved chunks, NULL on retrieval failure.
- The recording tracer: **1** trace, **1** retrieval span, **1** generation with
  the stub's tokens, per successful query.
- A tracer that raises everywhere: the same `AnswerResult` and row as with the
  no-op.
- An insert that fails (a `connect_fn` whose cursor raises on the insert):
  `logged=False`, the answer still returned.
- `sql/04` applied twice on a populated `query_log`: no error, rows intact.

**Manual, without a key:** `make bootstrap` twice; `make dev` shows the
not-configured message. **Manual, with a key (later):** one in-scope and one
out-of-scope question through `make dev`, the row and the trace read.

## Rollout plan

**BUILD order, two PRs, as BRAINSTORM chose:**

PR 1, the path:
1. ADR-021 (Planned) and its index row are already committed with this DESIGN.
2. `pip install -e .`; read the installed Langfuse 2.x API for the five calls.
3. `sql/04` + `make bootstrap`; contracts; `generation/sdk.py`;
   `observability/tracing.py`; `generation/answer.py`; config; tests.
4. `check_deploy_gate.py` + `make deploy`; test.
5. Mirrors: AGENTS.md (`sql/00`–`04` in the bootstrap boundary, the repo map),
   KB (`traces-and-generations.md`, the query_log columns), README roadmap items
   3, 5 and 6, ADR-009 (an in-place note that its span list is superseded by
   ADR-021's).

PR 2, the page: `ui/app.py`, the manual check without a key, BUILD_REPORT.

**Migration order:** `sql/04` runs in `make bootstrap` after `03`. An existing
local database gets the columns on the next bootstrap. No backfill: old rows keep
NULLs, which is what they are.

**No feature flag.** The page is gated by the key (no key, nothing runs) and its
publication by D7.

**Rollback:** revert the PRs. The added columns stay in any database that ran
`sql/04`. They are nullable or defaulted, so the old code ignores them. Removing
them is `make reset-db`, never the bootstrap.

## Open questions (for the author)

- [x] **D1. Where `answer()` lives:** `generation/answer.py`. It joins retrieval,
      generation, logging and tracing, and `generation/` is where the product path
      was promised ("the product path wraps it").
- [x] **D2. `corpus_commits` instead of `snapshot_ids`.** A deviation from
      DEFINE Q1, for the reason above. Plus `embedding_model` and `trace_id`, which
      Q1 did not list: the model distinguishes two embedding spaces under one
      commit, and the trace id joins a row to its trace.
- [x] **D3. `sql/04` as a new file**, following `03`'s precedent of one file per
      schema decision. It changes AGENTS.md's "`sql/00`–`03` are create-only" to
      `00`–`04`.
- [x] **D4. The cap: 500 characters.** It clears the longest evaluated question
      (216) by more than 2×. Q6 left the number to you.
- [x] **D5. Over-cap and empty questions write no row.** They are rejected before
      any query runs. The page's `max_chars` stops most of them earlier anyway.
- [x] **D6. A failed `query_log` insert does not fail the answer.** The visitor
      still gets it, the result says `logged=False`, and a warning is logged.
      "Exactly one row" holds whenever the database accepts the write. If
      retrieval failed because the database is down, the insert fails too, and
      only the local log records it.
- [x] **D7. Is a Streamlit Cloud app already connected to this repo?** If yes,
      merging PR 2 publishes the page, and the `make deploy` gate does not stop
      it. It would still be harmless while Streamlit Cloud has no
      `ANTHROPIC_API_KEY` secret (the page shows "not configured"), so the real
      gate is **not adding that secret before ADR-020 is Accepted**. ADR-021
      states both.
      **Answered 2026-10-05: no Streamlit Cloud app exists yet.** Creating one
      is part of the deploy, after ADR-020 is Accepted.
- [x] **D8. ADR-009 gets an in-place note** that its span list (intent
      classification, hybrid retrieval, reranking, threshold check) is superseded
      by ADR-021's trace shape. Its Decision text is not rewritten.
