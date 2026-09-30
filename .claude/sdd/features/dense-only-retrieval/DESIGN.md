# DESIGN: Honest dense-only retrieval

> Implements [DEFINE.md](DEFINE.md). Decision recorded in
> [ADR-018](../../../../docs/adr/ADR-018-dense-only-retrieval.md).

## Metadata

| Field | Value |
|-------|-------|
| Feature | dense-only-retrieval |
| Depends on | [DEFINE.md](DEFINE.md), Clarity Score 14/15, Ready for Design |
| Status | Draft |
| ADR needed | **Yes**: [ADR-018](../../../../docs/adr/ADR-018-dense-only-retrieval.md), Status Planned. BUILD's first reading decides it through the rule copied from DEFINE (checked byte-identical at DESIGN time) |

## Architecture overview

Two commits, and the second one depends on the Outcome.

```
Commit 1, measured (behaviour change only)
  retrieval/hybrid_search.py
    HYBRID_QUERY           sparse CTE, tsquery and fusion removed. One ranked list
                           ADR-018 Decision holds the full SQL
    search()               drops query_text. It never reaches SQL now
  retrieval/pipeline.py    stops passing query_text
  scripts/retrieval_recall.py   --baseline adds "identical rankings" over the
                           baseline's sparse-empty questions (A4)
  sql/99_verify.sql §5     mirrors the new query (uses no question text)
  tests                    see Test plan

Commit 2a, if Accepted (behaviour-neutral + docs)
  rename  hybrid_search.py → dense_search.py, HYBRID_QUERY → DENSE_QUERY,
          build_hybrid_query → build_dense_query, test files likewise
  docs    README ×6, AGENTS.md ×3, ADR-003 → Superseded, KB, schema COMMENTs
  proof   a recall run after the rename reproduces commit 1's artifact exactly

Commit 2b, if Rejected (the pre-agreed fallback, BRAINSTORM Option 3)
  revert  commit 1's query and search() signature. The recall A4 line stays
  docs    every claim rewritten to say what today's query does
```

**Q3 (what `rrf_score` holds): `1/(60 + dense_rank)`.** That is exactly what a
dense-only chunk scores under today's fusion. So:
- for the 43 sparse-empty questions, rankings **and** scores are identical
  (DEFINE A4 checks the rankings; the scores coming out equal too is a free
  second check)
- `ask.py`, the recall report and `top_rrf_scores` read the same across the
  change
- no contract change

Renaming the field or making it a cosine similarity is BRAINSTORM Option 4. That
is the fallback ADR's decision. `sparse_score = 0.0` and `sparse_rank = None`
already mean "the sparse side did not rank it" in the contract and in `ask.py`
(which prints `—`).

**Q4 (renames): yes, but only after acceptance, in their own commit.** The
measured commit changes behaviour and nothing else, so the reading attributes to
one thing. A rename before the Outcome would also have to be undone on rejection.
The rename is proven neutral by re-running recall and diffing the artifact
against commit 1's. `settings.hybrid_top_k` / `HYBRID_TOP_K` keeps its name. It
is an environment variable in deployments, and it goes in README Known Gaps as a
naming gap. Superseded and rejected ADRs keep the old names (ADR discipline).

**The search stays exact (ADR-018 Decision).** Seq scan over 304 rows with an `id`
tiebreak. HNSW would make it approximate, and the A4 identity check needs exact.

## Data contracts

None change. `RetrievedChunk` keeps every field. Under dense-only:

| field | value |
|---|---|
| `dense_distance`, `dense_rank` | as today |
| `sparse_score` | always `0.0` |
| `sparse_rank` | always `None` |
| `rrf_score` | `1/(RRF_K + dense_rank)` |

The recall artifact gains, in `summary` when `--baseline` is given:
`"identical_rankings": {"identical": N, "of": M, "differ": [qid, …]}`. M counts
the baseline questions whose ranking had no `sparse_rank`. "Identical" means the
top-20 list of `(rank, project, path, anchor)` is equal.

## Interfaces

| Where | Change |
|---|---|
| `hybrid_search.search(conn, *, query_vector, collections, top_k)` | `query_text` removed. Its only use was the tsquery |
| `pipeline.retrieve(question, …)` | Unchanged signature. Stops passing the text on |
| `hybrid_search.HYBRID_QUERY` | ADR-018's SQL. No `%(query_text)s` parameter |
| `scripts/retrieval_recall.py --baseline` | Adds the identical-rankings line. Relabels its header from "ADR-017 decision-rule inputs" to "decision-rule inputs", since ADR-018 reads the same A1–A3 |
| `config.py` | Nothing |
| `make ask` | Unchanged. The sparse column prints `—` everywhere. Dropping that column is part of commit 2a |

## Retrieval and RAG-specific concerns

- [x] **Chunking:** not affected.
- [x] **HNSW:** not touched, no reindex. Deliberately not used by the query
      (exactness, ADR-018 Alternative 6).
- [x] **Query pattern:** changes. `sql/99_verify.sql` §5 gets the dense-only query
      and a fresh `EXPLAIN ANALYZE` in commit 1. It uses the first chunk's embedding
      and no question text, so running it reads nothing from the golden set.
- [x] **RAGAS:** cannot run (`run_evaluation.py` is a stub, no API key). **Regression
      risk: yes, but confined.** Only the 7 sparse-active questions can change
      (DEFINE), and A1–A3 guard what the LLM sees. Source recall stands in
      (ADR-014).
- [x] **Fallback:** the top score stays `1/61` for every question (P2). Reported,
      not gated. The fallback ADR owns the fix.
- [x] **KB:** `rag/hybrid-retrieval.md` is rewritten in commit 2a or 2b to the state
      the Outcome leaves. `pgvector/hnsw-tuning.md`, `pydantic/*.md` and
      `langfuse/python-sdk.md` name `hybrid_search` or `hybrid_top_k` and get
      updated with the rename (KB drift rule).

## Alternatives considered

The decision's alternatives are in ADR-018. The design-level ones:

- **Rename in the measured commit.** Rejected. It mixes a behaviour change with a
  neutral one in the reading, and it makes a rejection revert larger.
- **Keep `query_text` in `search()` as an unused parameter,** so fewer call sites
  change. Rejected. An unused parameter tells a reader the text still matters.
- **Delete `sparse_score` / `sparse_rank` / `rrf_score` from the contract.**
  Rejected for now. It is contract churn that BRAINSTORM Option 4 will redo when the
  score gets a meaning. The fields are documented as constant instead.
- **Keep the integration sanitising tests** (quotes, `&`, `|`, `:*`, …). Rejected
  for commit 1. `search()` no longer takes text, so they would test nothing.
  They come back with the query if ADR-018 is rejected (commit 2b is a revert).
  A unit test asserts the query has no text parameter and no `tsquery`.

## Test plan

**Unit** (`tests/unit/test_hybrid_search_query.py`):

- the query contains none of `tsquery`, `ts_rank_cd`, `content_tsv`,
  `%(query_text)s`
- the query still selects every column the contract needs (existing tests,
  unchanged)
- `ROW_NUMBER() OVER (ORDER BY dense_dist ASC, id ASC)` and `ORDER BY dense_dist
  ASC, id ASC\n  LIMIT %(top_k)s` present (tiebreak)
- `rrf_score` is `1.0 / (%(rrf_k)s + d.dense_rank)`, and `999` does not appear
- `LIMIT %(top_k)s` appears exactly once, and no literal `LIMIT 20`
- `row_to_chunk` tests unchanged. They build rows by hand
- recall script: `identical_rankings` on hand-built artifacts: an identical one,
  one that differs in anchor, and a baseline question with sparse rows excluded
  from M

**Integration** (`tests/integration/test_hybrid_search_postgres.py`, real Postgres):

- **ranking is dense order:** the fixture's A, C, B (distances 0.0, 0.4, 1.0).
  B matches the text but now ranks 3rd (DEFINE acceptance test). Replaces
  `test_ranking_matches_rrf_computed_by_hand`, and scores are asserted as
  `1/61, 1/62, 1/63`
- **no sparse side:** every chunk has `sparse_rank is None` and `sparse_score == 0.0`
- **distance tiebreak by id:** two chunks with identical vectors. The lower id
  ranks first after the heap rewrite (the existing tiebreak test, moved to the
  dense side)
- **top_k, determinism, collection filter, empty index, full contract:**
  existing tests, with `text=` removed from `run()`
- **removed:** `test_a_sparse_only_chunk_gets_no_phantom_dense_contribution`,
  `test_dense_distance_is_real_even_for_a_sparse_only_match`, the no-lexeme and
  tsquery-syntax sanitising tests, and the quote/backslash test. Each tests the
  sparse side, which no longer exists. Listed in the BUILD_REPORT
- `test_retrieval_pipeline.py`: its mocks of `search` drop `query_text`

**Manual, on the local index** (BUILD, in this order):

1. Check that ADR-018's rule is byte-identical to DEFINE's. Done at DESIGN time;
   repeat it right before step 4
2. `make lint`, `make test`, `make bootstrap` against the populated DB (a no-op,
   no `DROP`)
3. Confirm the index is still `f1295df9` / `82a2e269` / `BAAI/bge-small-en-v1.5`.
   `--baseline` refuses otherwise
4. `make retrieval-recall baseline=.claude/dev/reports/retrieval-recall-20260929-190639.json`,
   twice. The two runs must be identical
5. Read A1–A4 and apply ADR-018's table. Write the Outcome, then commit 2a or 2b
6. `make verify-indexes` (§5 plan into the BUILD_REPORT)
7. On 2a: re-run recall after the rename and diff `results` against step 4's
   artifact. They must be equal. Then run the DEFINE `grep` over README, AGENTS.md
   and the KB, and list the remaining hits in the BUILD_REPORT

## Rollout plan

- **Migration:** none. No schema, no index, no reindex. `make bootstrap` stays a
  no-op on a populated DB.
- **Feature flag:** none. A mode switch was discarded in BRAINSTORM.
- **Order:** ADR-018 (Planned) is committed before code. Then commit 1, the
  measurement, the Outcome, and commit 2a or 2b.
- **If Accepted (2a):** ADR-018 → Accepted with the Outcome. ADR-003 → Superseded
  by ADR-018, in place. README: the Why line, the mermaid node, the tree node and
  the stack row say dense retrieval. The Known Gaps hybrid bullet is replaced by
  the `HYBRID_TOP_K` naming gap and the fallback-score gap, and next steps point to
  the fallback ADR. AGENTS.md: the stack's sparse line, the repo map and the
  pgvector-discipline hybrid bullet. KB updated. The `COMMENT ON` for
  `content_tsv` and the GIN index say "unused by retrieval since ADR-018".
  `COMMENT ON` is idempotent and not a `DROP`.
- **If Rejected (2b, rollback):** `git revert` of commit 1's query and signature
  changes. The recall script's identical-rankings line stays, since it is
  additive. ADR-018 → Rejected in place with the numbers. The docs take BRAINSTORM
  Option 3's wording: "dense retrieval, plus an exact-match sparse vote that fires
  only when one chunk contains every query term". README Known Gaps is updated to
  match.
- **What breaks on revert:** nothing downstream. The contract is unchanged, and
  `search()`'s only callers are `pipeline.retrieve` and tests.

## Open questions

- [x] **Q1, Q2 (DEFINE):** settled by the author on 2026-09-30.
- [x] **Q3:** `rrf_score = 1/(60 + dense_rank)`, contract unchanged (Architecture
      overview).
- [x] **Q4:** rename on acceptance, in its own behaviour-neutral commit.
      `HYBRID_TOP_K` stays and becomes a named gap.
- [ ] **Deferred to the fallback ADR:** what score the fallback reads (BRAINSTORM
      Option 4) and its threshold value (ADR-006).
- [ ] **Deviation from DEFINE's wording, flagged:** DEFINE said ADR-003 is
      "superseded in part". The design supersedes it wholly, because its decision
      (fuse two lists) is fully replaced. Only `RRF_K` survives, as a compatibility
      formula for the score.
