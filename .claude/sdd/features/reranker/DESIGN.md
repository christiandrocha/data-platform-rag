# DESIGN: Reranking the top-20 (ADR-005)

> Implements [DEFINE.md](DEFINE.md). Decision recorded in
> [ADR-005](../../../../docs/adr/ADR-005-cross-encoder-reranking.md).

## Metadata

| Field | Value |
|-------|-------|
| Feature | reranker |
| Depends on | [DEFINE.md](DEFINE.md) — Clarity Score 13/15 |
| Status | Draft |
| ADR needed | **Yes** — ADR-005, written now with status Planned; BUILD's measurement promotes it, with the model the rule picks, or rejects it |

## Architecture overview

One new module, one new pipeline function, one contract field. Retrieval as it
exists is not modified.

```
retrieve(question)                    unchanged: RRF top settings.hybrid_top_k
      │  list[RetrievedChunk]  (20)
      ▼
rerank(question, candidates, top_k)   NEW  retrieval/reranker.py
      │  list[RerankedChunk]   (top_k; default settings.rerank_top_k = 3)
      ▼
retrieve_and_rerank(question)         NEW  retrieval/pipeline.py — the two, composed
```

**`retrieve()` is not changed to rerank by default** (DEFINE open question 2).
`make retrieval-recall` needs the pre-rerank list to report before and after from
one retrieval, and ADR-014's metric stays defined on it. A new function composes
the two; generation will call that one.

### `retrieval/reranker.py`

- **`get_model()`**: `@lru_cache(maxsize=1)`, loads
  `CrossEncoder(get_settings_without_llm().reranker_model)`. Same pattern as
  `indexer/embedder.get_model()`, including `SystemExit` with an install hint on
  failure. It uses the no-LLM settings accessor because `make ask` and
  `make retrieval-recall` call no LLM (DEFINE open question 1). **Cost, measured
  in BRAINSTORM:** a cached load of 5.0 s (MiniLM) or 6.2 s (bge), paid on the
  first rerank of a process; the first download was 27.5 s and 75.5 s.
- **`rerank(question, candidates, top_k=None) -> list[RerankedChunk]`**
  1. Empty `candidates` returns `[]` **before** `get_model()` is called.
  2. It builds one pair per candidate, `(question, chunk.content)`, and makes
     **one** `predict` call over all of them.
  3. It counts tokens per pair with the model's own tokenizer, with truncation
     off, and compares against `model.max_seq_length`. A pair over the limit is
     **scored truncated and flagged**, not dropped (DEFINE open question 3).
     Dropping it would remove a candidate, which changes recall by removing a
     candidate rather than by ranking it — the thing being measured.
  4. It sorts by `(-rerank_score, -rrf_score, id)`: rerank score first, then
     RRF order, then id. RRF order is itself id-tiebroken since
     `sparse-query-strategy`, but the key does not rely on the input arriving
     sorted.
  5. It returns the first `top_k`, where `None` means `settings.rerank_top_k`.
     The recall script passes `top_k=len(candidates)` to get the full reordering.
- **The score is `predict`'s raw output, stored as is.** The two models' outputs
  are not on a common scale, and whether `predict` applies a sigmoid depends on
  the model's own config. BUILD records which activation each model used. No
  code compares a rerank score against a constant (the fallback is a non-goal).

## Data contracts

**One field added, no default:**

```diff
 class RerankedChunk(RetrievedChunk):
     """RetrievedChunk augmented with cross-encoder rerank score."""

     rerank_score: float
+    # True when (question, content) exceeded the model's window and was scored on
+    # a truncated pair. Required, not defaulted: a default of False would assert
+    # "not truncated" about a chunk nobody measured.
+    truncated: bool
```

- Two existing constructions in `tests/unit/test_contracts.py` gain
  `truncated=False`. `AnswerResult.top_chunks` inherits the field unchanged.
- **KB mirror.** `.claude/kb/pydantic/models.md` gains the field. Its
  `RetrievedChunk` copy also gains `dense_rank` and `sparse_rank`, which it has
  been missing since `retrieval`.
- No table, no column, no migration.

## Interfaces

- **New:** `reranker.rerank(...)`, `reranker.get_model()`,
  `pipeline.retrieve_and_rerank(question, collections=None, conn=None) -> list[RerankedChunk]`.
- **Unchanged:** `retrieve()`, `search()`, `build_hybrid_query()`.
- **`make ask`** reranks by default and prints `rerank_top_k` rows, with a `rerank`
  column before `rrf`. `--no-rerank` (make: `NO_RERANK=1`) prints the RRF top 20
  as today.
- **`make retrieval-recall`** always reranks. Per question it retrieves once,
  reranks all 20, and reads k=3/10/20 off both orderings. The artifact adds:
  - `reranker`: model name, total truncated pairs, per-question latency in
    seconds (the DEFINE COULD);
  - `summary.reranked_recall_at_k`, beside the unchanged `source_recall_at_k`;
  - `summary.top_rerank_scores` (q005 included);
  - per result: `reranked_at_k` and `reranked_ranking`.

  The gainable/protected/unreachable groups are **not** coded into the script.
  They were fixed from one artifact and would rot there; BUILD_REPORT applies
  them by hand.
- **Config:** nothing added. `settings.reranker_model` / `RERANKER_MODEL` already
  exist and switch the model with no code change. **The default does not change
  in this DESIGN**; BUILD changes it only if the rule picks MiniLM.

## Retrieval and RAG-specific concerns

- [x] **Chunking** — unaffected. The truncation count is the check on ADR-007's
      cap under a second tokenizer, and the fix, if needed, is not here.
- [x] **HNSW index** — untouched; no reindex.
- [x] **Query pattern** — the SQL is unchanged; `sql/99_verify.sql` does not move.
- [x] **RAGAS** — does not exist. The measure is source recall at k=3 before and
      after reranking, under DEFINE's rule.

## Files that name the reranker model

Only BUILD knows which model ships, so each file's treatment depends on the
verdict:

| file | if MiniLM ships | if bge ships | if neither |
|---|---|---|---|
| `data_platform_rag/config.py` default | change | keep | keep |
| `.env.example` | change | keep | keep |
| AGENTS.md stack line | change, with measured latency | keep, add measured latency | say reranking was measured and rejected |
| README lines 40, 87 | change | keep | remove the reranker from the diagram, noted as rejected |
| **README line 111, "~100ms latency"** | **correct in every case** — measured 2.4–16.2 s per question | | |
| `docs/adr/index.md` row title | neutral title now: "Cross-encoder reranking of the RRF top 20", status per verdict | | |
| `ARCHITECTURE.md`, `rag-architect.md` | change | keep | mark as rejected |
| KB `config-pattern.md` | refer to `settings.reranker_model`; **also fix `rerank_top_k` default=5 → `settings.rerank_top_k` (currently 3)** | | |
| KB `cost-tracking.md` | refer to `settings.reranker_model` | | |
| ADR-004 line 81, `PRE_BUILD_VALIDATION.md` | **keep as historical**: records of what was planned at the time; ADR-005 supersedes them | | |

## Alternatives considered

- **Rerank inside `retrieve()`** — one entry point, but the recall script loses
  the pre-rerank list, and ADR-014's metric would silently change its meaning.
- **Drop truncated pairs** — the candidate set would shrink under measurement.
- **Truncation count on a result wrapper** (`RerankResult(chunks, truncated_pairs)`)
  — a second contract where a per-chunk field says the same thing and travels
  with the chunk into generation and logs.
- **Normalise scores (sigmoid) in code** — it would imply a comparable scale that
  the two models do not share, and it serves only the fallback, a non-goal.
- The model choices themselves (bge vs MiniLM, collapse, LLM, hosted API) are in
  BRAINSTORM and ADR-005, not repeated here.

## Test plan

**Unit** (`tests/unit/test_reranker.py`, fake `CrossEncoder` with scripted
scores and a fake tokenizer; `get_model` monkeypatched, so no model is loaded):

1. Reorders by rerank score.
2. A tie on rerank score is broken by higher `rrf_score`.
3. A tie on both is broken by lower `id`.
4. An empty list returns `[]`, and `get_model` is never called (the fake raises if it is).
5. `top_k=3` given 5 candidates returns 3; given 2, it returns 2.
6. `top_k=None` uses `settings.rerank_top_k`.
7. A pair over the fake window is `truncated=True`; the others `False`.
8. Every `RetrievedChunk` field survives unchanged into `RerankedChunk`.
9. `predict` is called **once**, with `(question, content)` pairs in candidate order.
10. `retrieve_and_rerank` passes `hybrid_top_k` to `retrieve` and
    `rerank_top_k` to `rerank` (both monkeypatched).
11. `RerankedChunk` without `truncated` fails validation.
12. The recall script's `evaluate` produces pre and post rankings from one
    retrieval (both stages monkeypatched).

**Integration:** none new. Hybrid search is untouched, and a real model in the
suite would break the no-network posture.

**Manual** (local index, 304 rows, same snapshot):

13. `make test` with `HF_HUB_OFFLINE=1` and an empty `HF_HOME`: green (DEFINE acceptance).
14. `make ask` with q002's question: 3 rows, rerank column populated.
15. `make retrieval-recall` twice per model via `RERANKER_MODEL`: identical pairs of artifacts.
16. The DEFINE rule applied to the two artifacts, by hand, in BUILD_REPORT.

## Rollout plan

- **Migration:** none.
- **Feature flag:** none. No downstream stage exists yet (generation is
  unbuilt), and `make ask --no-rerank` keeps the old view.
- **Rollback / the "neither ships" verdict:** as with ADR-015, the stage is
  reverted: `reranker.py`, `retrieve_and_rerank`, the `make ask` default and the
  recall script's post-rerank fields. The `truncated` field goes with it, since
  nothing else produces a `RerankedChunk`. ADR-005 is marked Rejected in place,
  with the numbers. The README "~100ms" correction stays either way.
- **Model download:** the first run of the shipped model downloads it (92 MB or
  1,134 MB). CI never does, because `make test` loads no model.

## Open questions

- [ ] **Which activation does each model's `predict` apply?** Recorded in BUILD
      from the models' configs, not assumed here.
- [ ] **Does a 2.4–2.8 s rerank belong in `make ask` by default?** Chosen here
      as the default because DEFINE's acceptance test asks for it; revisit if it
      makes the curator's loop too slow.
- [ ] **Carried from DEFINE:** latency optimisation opens only if the bge row fires.
