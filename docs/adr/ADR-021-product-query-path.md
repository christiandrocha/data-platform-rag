# ADR-021 — The product query path: one row, one trace, gated publication

**Status**: Planned — 2026-10-05. Accepted when BUILD lands
**Date**: 2026-10-05

## Context

Nothing turns a visitor's question into an answer. `retrieval/pipeline.py`
retrieves and `generation/client.py` generates, but the client is ADR-020's
evaluation path: it writes no `query_log` row and no Langfuse trace. AGENTS.md
requires both for every user query. `query_log` is the analytics source of
truth, and Langfuse is the observability source of truth and the place RAGAS
scores attach (ADR-009).

The structures meant to carry a product query describe a pipeline that no longer
exists:

- `AnswerResult` carries `intent`, `top_chunks: list[RerankedChunk]` and
  `top_score`. There is no intent classifier, ADR-005 rejected the reranker, and
  ADR-019 superseded the score gate. Nothing imports it.
- `query_log` has `intent` and `reranker_top_score`, which nothing would fill. It
  has no column for ADR-020's output class, the model, the prompt version, the
  tokens, or the corpus that answered.
- ADR-009's span list (intent classification, hybrid retrieval, reranking,
  threshold check, generation) names three stages that do not run.

Rule 3 is the only out-of-scope gate, and ADR-020 has not measured it yet. A
public page answering before that measurement exposes visitors to the risk
ADR-006 named: a fabricated answer that looks grounded.

## Decision

**One function, `generation/answer.py :: answer()`, is the product path.** It
retrieves once (default collections, top `settings.rerank_top_k`), generates
under `SYSTEM_PROMPT`, classifies the text with ADR-020's `classify_output()`,
writes one `query_log` row and emits one Langfuse trace. Retrieval, prompt,
context format and model are exactly ADR-020's. This ADR changes none of them.

**What the visitor sees follows the class:** an answer with its sources; the
fixed `FALLBACK_MESSAGE` for `fallback` and for `empty`; the model's own text for
`non_compliant_refusal`, which carries the LinkedIn link. A failed query (an
exception in retrieval or the call) shows a fixed "could not answer right now"
message, never the fallback, because a failure says nothing about scope.

**`query_log` gains columns, never loses them.** `sql/04_query_log_product.sql`
adds, with `ADD COLUMN IF NOT EXISTS`: `output_class`, `failed`, `error`,
`model`, `system_prompt_version`, `context_format_version`, `input_tokens`,
`output_tokens`, `stop_reason`, `corpus_commits`, `embedding_model`, `trace_id`.
`intent` and `reranker_top_score` stay, always NULL, with a comment saying why.
`corpus_commits` holds `project@sha` taken from the retrieved chunks in the
insert itself. Snapshot ids would not do: a reindex deletes the snapshot row and
its replacement gets a new id (ADR-013). `fallback_fired` is true for `fallback`,
`non_compliant_refusal` and `empty`, which is ADR-020's B2 grouping: the visitor
got no answer.

**The trace has the shape the system now runs:** a `query` trace, a
`dense_retrieval` span, an `anthropic_call` generation with token usage. This
supersedes ADR-009's span list. ADR-009's other decisions stand. One wrapper
module (`observability/tracing.py`) catches every Langfuse exception, so "never
block on Langfuse" lives in one place.

**A failed `query_log` insert does not fail the answer.** The result records
`logged=False` and a warning is logged. An empty question, or one longer than
`settings.max_question_chars`, is rejected before anything runs and writes no
row.

**Publication waits for ADR-020.** Two gates, because one is not enough:

1. `make deploy` runs `scripts/check_deploy_gate.py`, which refuses unless
   ADR-020's Status starts with `Accepted`.
2. `make deploy` is a `git push`, so a Streamlit Cloud app tracking `main` would
   publish on any merge. The gate that holds there is the key. Without
   `ANTHROPIC_API_KEY` the page shows "generation is not configured" and runs
   nothing. **The key is not added to Streamlit Cloud's secrets before ADR-020
   is Accepted.** On 2026-10-05 no Streamlit Cloud app exists yet; creating
   one is part of the deploy, after ADR-020 is Accepted.

## Consequences

**Every product query is recorded twice, by design.** Postgres for analytics,
Langfuse for traces and scores. Either can fail without the other failing, and
neither failure reaches the visitor.

**Questions are stored as text** in `query_log` and in Langfuse. ADR-009 accepted
this for a public demo. The page says, in one line, that questions are logged.

**Old `query_log` rows keep NULLs** in the new columns. No backfill: they were
written before the columns existed.

**The bootstrap boundary grows by one file.** AGENTS.md's "`sql/00`–`03` are
create-only" becomes `00`–`04`. The new file holds no `DROP`, and rolling back
the code leaves the columns in place, unused.

**No latency or cost number is claimed.** The first real ones come from the first
query with a key, recorded in `query_log` and the trace.

**`RerankedChunk` is deleted** with the old `AnswerResult`. A reranker that
returns adds its own field when it is measured in.

## Alternatives considered

**1. Fill the old `AnswerResult` with placeholders.** It would record an intent
no classifier produced and a score no gate reads. A contract that records
invented values is worse than a rewrite with no importers.

**2. Record `snapshot_ids`.** They dangle after a reindex, as `retrieved_ids`
already does. `corpus_commits` survives it.

**3. Gate publication only in `make deploy`.** It does not stop a Streamlit Cloud
app that deploys on push. The key gate does.

**4. Show the fallback on a failed query.** It tells the visitor the question is
out of scope when nothing decided that, and it mixes failures into the
`fallback_fired` analytics.

**5. Wrap each Langfuse call in place.** Several copies of one guard, and a missed
copy breaks the rule. One module holds it.
