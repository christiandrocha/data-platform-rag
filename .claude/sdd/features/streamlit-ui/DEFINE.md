# DEFINE: The product query path, and the page a visitor asks on

> One function that turns a visitor's question into an answer or the fallback,
> and records it in `query_log` and Langfuse, and a Streamlit page over it. Built
> and tested without an API key. Not deployed until ADR-020 is Accepted.

## Metadata

| Field | Value |
|-------|-------|
| Feature | streamlit-ui |
| Date | 2026-10-05 |
| Author | christiandrocha (decisions), Claude (draft) |
| Status | Ready for Design (Q1–Q6 approved as proposed by the author on 2026-10-05; Q6's number is set in DESIGN) |
| Clarity Score | 13/15 |
| ADR | ADR-021 (written in DESIGN): the `query_log` columns, the trace shape, the deploy gate |
| Brainstorm | [BRAINSTORM.md](BRAINSTORM.md), Option 1, confirmed by the author on 2026-10-05 |
| Key | **No API key exists.** Everything here is built and tested on a stub client. The first real answer waits for the key, as ADR-020's measurement does |

## Problem statement

A visitor cannot ask the project anything: `ui/app.py` is a placeholder, and no
code joins retrieval and generation into a product query. The one generation
path that exists, `generation/client.py`, is the evaluation path: it writes no
`query_log` row and no Langfuse trace, which AGENTS.md requires for every user
query. The contract that should carry a product answer, `AnswerResult`, and the
`query_log` table still describe the pipeline before ADR-018 and ADR-019
(intent, reranker score, score gate), so neither can record a query as it now
runs.

## Users

| User | Role | Pain point |
|------|------|-----------|
| A visitor (recruiter or engineer) | Asks about the two platforms' decisions | There is no page to ask on |
| The author | Owns the product and its public claims | Cannot see what visitors ask, what it cost, or whether rule 3 fired, because nothing is recorded |
| A future RAGAS run | Scores answers against the trace that produced them (ADR-009) | No trace exists to attach a score to |

## Definitions

- **The product path:** `answer(question, client, conn)`. It retrieves once with
  default collections and the top `settings.rerank_top_k` chunks, calls
  `generate()` under `SYSTEM_PROMPT`, classifies the text with
  `classify_output()` (ADR-020's four classes), writes one `query_log` row, and
  emits one Langfuse trace. The model, prompt and context format are the ones
  ADR-020 measures. The product path adds no retrieval or prompt change.
- **What the visitor sees, per class** (Q2 proposes this):

  | class | shown |
  |---|---|
  | answer | the text, then its sources: project, path and ADR id of each chunk in the context |
  | fallback | `FALLBACK_MESSAGE`, no sources |
  | non_compliant_refusal | the text as returned (it carries the LinkedIn link), no sources |
  | empty | `FALLBACK_MESSAGE`, no sources. The row records `empty` |

- **A failed query:** retrieval raises, or the Anthropic call still fails after
  the SDK's retries. The visitor sees a fixed "could not answer right now"
  message. It is not the fallback, because nothing decided the question was out
  of scope (Q3).

## Goals (prioritized)

| Priority | Goal |
|----------|------|
| MUST | `answer()` in `retrieval/pipeline.py` or a new `generation/answer.py` (DESIGN picks), returning a rewritten `AnswerResult`: question, output class, text shown, sources, model, prompt and context versions, tokens, stop reason, latency, trace id. The old fields (`intent`, `top_chunks: list[RerankedChunk]`, `top_score`) are removed |
| MUST | Exactly **one** `query_log` row per query, failed queries included. New columns (Q1) added with `ALTER TABLE … ADD COLUMN IF NOT EXISTS` in the create-only bootstrap. No `DROP` outside `sql/90_reset.sql` |
| MUST | Exactly **one** Langfuse trace per query: a `retrieval` span and an Anthropic `generation` with tokens. Fire-and-forget: a Langfuse error is logged and the visitor still gets the answer. `LANGFUSE_ENABLED=false` runs the same code on the no-op client |
| MUST | The page: a question box, the answer or fallback, the sources under an answer, and the per-class display above |
| MUST | Without a key, the page says generation is not configured, and makes no call and no write (Q4) |
| MUST | `make deploy` refuses unless ADR-020's Status is Accepted (Q5) |
| MUST | Every test runs on a stub client and a recording fake Langfuse. No test calls the API or needs a key |
| SHOULD | A question length cap, enforced before retrieval (Q6) |
| SHOULD | The page states, in one line, that questions are logged (ADR-009 flags that traces hold query text) |
| COULD | `make ask q=… generate=1`, the CLI over the same `answer()` (deferred from ADR-020's DESIGN) |

## Success criteria (measurable)

All checkable without a key:

- [ ] **1** `query_log` row per `answer()` call, in each of the four classes and
      in the failed case: 6 cases, each asserted by count on the local database.
- [ ] **1** trace per call on the recording fake, holding **1** retrieval span and
      **1** generation with the stub's token counts.
- [ ] **0** exceptions reach the visitor when the Langfuse client raises on every
      method: the answer is returned and the row is still written.
- [ ] **0** API calls and **0** rows when the key is empty.
- [ ] `make deploy` exits non-zero while ADR-020 reads Planned: **1** test.
- [ ] `make lint`, `make test`: exit 0.

The first real answer, its tokens and its latency are measured when a key
exists. No latency or cost number is set here, because none has been measured
(never substitute an estimate).

## Acceptance tests

- [ ] A stub returning an answer: the result's class is `answer`, its sources
      match the retrieved chunks in rank order, and the row's columns match the
      result.
- [ ] A stub returning `FALLBACK_MESSAGE` with whitespace around it: class
      `fallback`, `fallback_fired` true, no sources shown.
- [ ] A stub returning "" : class `empty`, the visitor sees `FALLBACK_MESSAGE`,
      the row records `empty`.
- [ ] A stub that raises: the failed-query message, one row marked failed, no
      exception out of `answer()`.
- [ ] A Langfuse fake that raises everywhere: same result as with the no-op.
- [ ] `make bootstrap` twice against a populated database: no error, no data
      lost, the new columns present.
- [ ] Manual, without a key: `make dev` against the local database shows the
      not-configured message.
- [ ] Manual, **when a key exists**: one in-scope and one out-of-scope question
      through `make dev`, with the row and the trace inspected.

## Non-goals

- Deploying. The page goes public only after ADR-020 is Accepted.
- Any change to retrieval, the prompt, the model or the fallback mechanism.
- The intent classifier, streaming, thumbs up/down, a response cache (README
  deferred list).
- Upgrading the Langfuse SDK past 2.x.
- RAGAS, and pushing scores to traces. This feature makes the trace they attach
  to.
- Multi-turn conversation. One question, one answer.

## Open questions

- [x] **Q1 (author). `query_log` columns.** Proposed new columns: `output_class`,
      `failed` (with `error` text), `model`, `system_prompt_version`,
      `context_format_version`, `input_tokens`, `output_tokens`, `stop_reason`,
      `snapshot_ids BIGINT[]`. The snapshot ids matter because reindexing
      replaces chunks (ADR-013), so `retrieved_ids` can point at rows that no
      longer exist. `intent` and `reranker_top_score` stay, always NULL, with a
      comment saying why. They are never dropped from the bootstrap path.
- [x] **Q2 (author). What the visitor sees per class.** The table above. The
      choice to flag: `empty` shows `FALLBACK_MESSAGE` (a dead end either way, and
      the fixed message is better than a blank), while `non_compliant_refusal`
      shows the model's own text (it already carries the link).
- [x] **Q3 (author). A failed query** shows a fixed "could not answer right now"
      message, not the fallback. The fallback means "out of scope", and a
      timeout says nothing about scope.
- [x] **Q4 (author). Without a key** the page shows a not-configured message and
      runs nothing, not even retrieval. Showing ranked chunks without an answer
      is BRAINSTORM Option 3, which was not chosen.
- [x] **Q5 (author). The deploy gate is checked by code.** `make deploy` reads
      ADR-020's Status line and refuses unless it starts with Accepted. A human
      check can be forgotten. The page itself does not check, because it should
      run locally before the measurement.
- [x] **Q6 (author). The length cap.** A public page spends money per question.
      A cap on question length, applied before retrieval, bounds one question's
      input. The number is the author's: the longest golden-set question is the
      floor it must clear (DESIGN reports that length). A rate limit and a spend
      limit belong to the deploy, not here.

**Settled 2026-10-05: Q1–Q6 approved as proposed.** Q6's number is proposed in
DESIGN, against the measured longest golden-set question, and approved there.

## Clarity Score self-check

| Dimension | Score | Notes |
|-----------|-------|-------|
| Problem is specific and testable | 5 | The missing path, the stale contract and the stale table are named, with the AGENTS.md rules they break |
| Users are named and their pain is real | 4 | The visitor's pain is real but hypothetical until deploy. The author's (nothing recorded) is concrete |
| Success criteria include numbers | 4 | Counts per case, all testable without a key. No latency or cost number, deliberately: none is measured, and none will be estimated |
| **Total** | **13/15** | Ready for Design: Q1–Q6 approved on 2026-10-05 |
