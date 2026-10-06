# BUILD REPORT: Honest dense-only retrieval

## Metadata

| Field | Value |
|-------|-------|
| Feature | dense-only-retrieval |
| DEFINE | [DEFINE.md](DEFINE.md) |
| DESIGN | [DESIGN.md](DESIGN.md) |
| ADR | [ADR-018](../../../../docs/adr/ADR-018-dense-only-retrieval.md), **Accepted** 2026-09-30. Supersedes ADR-003 |
| Start date | 2026-09-30 |
| End date | 2026-09-30 |
| PR | [#24](https://github.com/christiandrocha/data-platform-rag/pull/24), merged by rebase 2026-10-02 |

## Outcome in one paragraph

Retrieval now ranks by cosine distance alone. The change was measured once
against the rule fixed in DEFINE and **accepted**. Nothing moved at k=3, k=10 or
k=20 (38 / 44 / 46). No top-3 path was lost. The 43 questions whose sparse side
was already empty ranked identically, and so did their scores. Of the 7
sparse-active questions, one declared path moved (q033, rank 1 → 2, still in the
top 3). All three predictions held. After the acceptance, the module was renamed
in a behaviour-neutral step, proven by a recall run identical to the measured
one. Every public claim of hybrid retrieval was rewritten.

## What was built

In order, cited by commit subject (the branch may be rebase-merged):

1. `docs(adr): ADR-018 planned -- dense-only retrieval`. ADR Planned, with the
   rule copied byte-identical from DEFINE, before any code.
2. `feat(retrieval): dense-only query (ADR-018, pre-measurement)`. The measured
   commit, behaviour only:
   - `HYBRID_QUERY`: sparse CTE, tsquery and fusion removed. Exact scan, `id`
     tiebreak, `sparse_score` 0.0, `sparse_rank` NULL, `rrf_score` `1/(60 + dense_rank)`
   - `search()` drops `query_text`, and `pipeline.retrieve` stops passing it
   - `scripts/retrieval_recall.py`: `identical_rankings` (ADR-018 A4) in
     `--baseline` and in the artifact's `summary`
   - `sql/99_verify.sql` §5 mirrors the dense-only query
   - tests rewritten (below)
3. This commit: ADR-018 Outcome, ADR-003 Superseded in place, ADR index, then the
   renames and the docs:
   - `retrieval/hybrid_search.py` → `retrieval/dense_search.py`, `HYBRID_QUERY` →
     `DENSE_QUERY`, `build_hybrid_query` → `build_dense_query`; test files likewise
   - `make ask` drops the sparse column
   - README: the Why line, the mermaid node, the architecture tree, the stack
     row, next steps, two Known Gaps (fallback score, `HYBRID_TOP_K` name), and the
     future-options row
   - AGENTS.md (and so CLAUDE.md): the stack line, the repo map, the pgvector
     discipline bullet
   - schema `COMMENT`s on `content_tsv` and its GIN index (applied by
     `make bootstrap`, a no-op on data), and the `pg_trgm` note
   - KB: `rag/hybrid-retrieval.md` → `rag/dense-retrieval.md` (rewritten),
     `rag/rag-architecture.md`, `pgvector/hnsw-tuning.md`, `langfuse/python-sdk.md`,
     `langfuse/traces-and-generations.md`, `pydantic/models.md`. Also the
     `rag-architect` agent's KB reference

**Tests.** Removed, because each tested the sparse side, which no longer exists:
`test_a_sparse_only_chunk_gets_no_phantom_dense_contribution`,
`test_dense_distance_is_real_even_for_a_sparse_only_match`,
`test_a_question_matching_no_text_still_returns_dense_results`, the parametrised
no-lexeme and tsquery-syntax sanitising tests, the quote/backslash test, and the
unit tests on the tsquery and the fusion. Added or rewritten: ranking is distance
alone (the fixture's text-matching chunk B now ranks 3rd), scores `1/61, 1/62,
1/63`, no sparse rank or score, the distance tiebreak by `id`, no tsquery or text
parameter in the query, exact scan, and three `identical_rankings` unit tests.
Test count 223 → 220.

## The measurement

Pre-measurement checks:

- ADR-018's rule is byte-identical to DEFINE's: `awk` range extract from both,
  then `diff`. 30 lines, no difference.
- Golden set unchanged. Index `f1295df9` / `82a2e269` / `BAAI/bge-small-en-v1.5`,
  304 chunks. `--baseline`'s comparability check passed.
- `make lint` clean, `make test` 220 passed / 3 skipped.
- `make bootstrap` on the populated database: 304 chunks and the same SHAs before
  and after.

`make retrieval-recall baseline=.claude/dev/reports/retrieval-recall-20260929-190639.json`,
twice (`-20260930-182007.json`, `-182023.json`; `results` and `summary` equal):

```
  A1  k=3 found:   38 -> 38 /57  (+0)
  A2  top-3 paths lost: 0
  A3  k=10 found:  44 -> 44 /57
      k=20 found:  46 -> 46 /57
      questions with sparse rows: 7 -> 0 /50  (ADR-017 A4)
      sparse-empty questions ranked identically: 43/43  (ADR-018 A4)
```

All four hold. The reading falls in the row "nothing moves at any k" →
**Accepted**. Details and predictions are in ADR-018's Outcome.

**Rename neutrality:** after the renames, `make retrieval-recall`
(`-20260930-182208.json`) has `results` equal to `-182007.json`.

## What deviated from design

- **ADR-003 is superseded wholly, not "in part"** as DEFINE worded it. This was
  already flagged in DESIGN.
- **The KB retrieval page was renamed**, `rag/hybrid-retrieval.md` →
  `rag/dense-retrieval.md`. DESIGN said "rewritten". A page named "hybrid" would
  have kept the false claim in its path. The one live reference, the
  `rag-architect` agent, was updated. Old feature records that cite the old path
  are history and were not changed.
- **DEFINE's grep acceptance test holds in intent, not in its letter.** It asked
  that every remaining `hybrid|sparse|tsvector` hit in README, AGENTS.md and the KB
  name ADR-018. The remaining hits are:
  - the intent label `hybrid` (README 37, 80; KB `pydantic/models.md` 15,
    `pydantic/llm-output-validation.md` 49–55). This is a classifier category
    meaning "both collections", not a retrieval method, so it is out of this ADR's
    reach.
  - `settings.hybrid_top_k` (README 196, which names ADR-018; KB
    `pydantic/config-pattern.md` 29, 56). The setting keeps its name by DESIGN.
  - the contract copy in `pydantic/models.md` (`sparse_score`, `sparse_rank`),
    whose docstring names ADR-018.
  - every other hit is in a line or section that names ADR-018, ADR-015 or
    ADR-017 as history.
- **`contracts.py` changed** (the `RetrievedChunk` docstring) although DESIGN said
  contracts do not change. The fields and types did not change, and its KB copy was
  updated in the same pass.
- **`seed(..., file_of=…)` in the integration tests is now unused.** It was kept
  from ADR-017 for "the next per-file rule", and it stays.

## RAGAS delta

**Not measured. `make eval` does not produce scores yet.** On 2026-09-30 it prints
`scripts/run_evaluation.py — not yet implemented (BUILD phase pending)`. No number
is written here (AGENTS.md: "Never invent RAGAS scores").

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Faithfulness | pending | pending | — |
| Context Precision | pending | pending | — |
| Answer Relevance | pending | pending | — |
| Context Recall | pending | pending | — |
| Fallback rate | pending | pending | — |

Source recall (ADR-014) stands in: 38 / 44 / 46 before and after.

## Query plan

`make verify-indexes` §5, run after the measurement: a Seq Scan over 304 rows
feeding one WindowAgg, no reference to `content_tsv`, 1.8 ms execution. §6 still
reports `Index Scan using idx_chunks_embedding_hnsw`.

```
                                                                    QUERY PLAN                                                                     
---------------------------------------------------------------------------------------------------------------------------------------------------
 Sort  (cost=84.89..84.96 rows=30 width=88) (actual time=1.776..1.779 rows=20 loops=1)
   Sort Key: d.dense_rank
   Sort Method: quicksort  Memory: 26kB
   Buffers: shared hit=1806
   CTE candidates
     ->  Seq Scan on chunks c_1  (cost=0.38..56.94 rows=304 width=16) (actual time=0.034..1.530 rows=304 loops=1)
           Filter: (collection = ANY ('{decisions,architecture}'::text[]))
           Buffers: shared hit=1803
           InitPlan 1 (returns $0)
             ->  Limit  (cost=0.15..0.38 rows=1 width=151) (actual time=0.006..0.006 rows=1 loops=1)
                   Buffers: shared hit=2
                   ->  Index Scan using chunks_pkey on chunks  (cost=0.15..70.96 rows=304 width=151) (actual time=0.005..0.005 rows=1 loops=1)
                         Buffers: shared hit=2
   ->  Hash Join  (cost=19.47..27.21 rows=30 width=88) (actual time=1.722..1.765 rows=20 loops=1)
         Hash Cond: (c.id = d.id)
         Buffers: shared hit=1803
         ->  CTE Scan on candidates c  (cost=0.00..6.08 rows=304 width=8) (actual time=0.035..0.052 rows=304 loops=1)
               Buffers: shared hit=9
         ->  Hash  (cost=19.22..19.22 rows=20 width=16) (actual time=1.679..1.680 rows=20 loops=1)
               Buckets: 1024  Batches: 1  Memory Usage: 9kB
               Buffers: shared hit=1794
               ->  Subquery Scan on d  (cost=18.62..19.22 rows=20 width=16) (actual time=1.662..1.671 rows=20 loops=1)
                     Buffers: shared hit=1794
                     ->  Limit  (cost=18.62..19.02 rows=20 width=24) (actual time=1.662..1.668 rows=20 loops=1)
                           Buffers: shared hit=1794
                           ->  WindowAgg  (cost=18.62..24.70 rows=304 width=24) (actual time=1.661..1.666 rows=20 loops=1)
                                 Buffers: shared hit=1794
                                 ->  Sort  (cost=18.62..19.38 rows=304 width=16) (actual time=1.653..1.654 rows=20 loops=1)
                                       Sort Key: candidates.dense_dist, candidates.id
                                       Sort Method: quicksort  Memory: 36kB
                                       Buffers: shared hit=1794
                                       ->  CTE Scan on candidates  (cost=0.00..6.08 rows=304 width=16) (actual time=0.000..1.563 rows=304 loops=1)
                                             Buffers: shared hit=1794
 Planning:
   Buffers: shared hit=5
 Planning Time: 0.192 ms
 Execution Time: 1.815 ms
```

## Known gaps at merge time

- **The fallback has no usable score.** The top `rrf_score` is `1/61` for every
  question (ADR-018 P2). A cosine similarity score and a calibrated ADR-006
  threshold are the next retrieval ADR. Recorded in README Known Gaps.
- **`HYBRID_TOP_K` keeps its name.** Recorded in README Known Gaps.
- **KB `rag/rag-architecture.md` principle 4** still says cross-encoder reranking
  gives "meaningful RAGAS lift". ADR-005 rejected reranking on 2026-09-21. This
  predates the feature and is flagged, not changed.
- **README Known Gaps still says "The golden set holds 5 of 50 questions."** It
  holds 50. This predates the feature and is flagged for the author.
- **3 integration tests skip** without `/tmp/dpr-corpus-*`. This predates the
  feature.

## Verification

- [x] `make lint` clean
- [x] `make test` green: 220 passed, 3 skipped
- [ ] `make eval` results attached: **not possible**, `run_evaluation.py` is a stub
- [x] `make verify-indexes` shows the expected plans (§5 above, §6 HNSW proof)
- [x] Two identical recall runs. The rule was applied once, to the first
- [x] The rename is neutral: recall `results` equal to the measured artifact
- [x] `make bootstrap` on the populated DB changes no data
