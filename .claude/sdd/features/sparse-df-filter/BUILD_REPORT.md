# BUILD REPORT: A sparse side that votes only on distinctive terms

## Metadata

| Field | Value |
|-------|-------|
| Feature | sparse-df-filter |
| DEFINE | [DEFINE.md](DEFINE.md) |
| DESIGN | [DESIGN.md](DESIGN.md) |
| ADR | [ADR-017](../../../../docs/adr/ADR-017-df-filtered-or-for-the-sparse-side.md), **Rejected** 2026-09-30 |
| Start date | 2026-09-30 |
| End date | 2026-09-30 |
| PR | [#23](https://github.com/christiandrocha/data-platform-rag/pull/23), merged by rebase 2026-10-02 |

## Outcome in one paragraph

The filter was built as designed, tested, measured once on the fixed snapshot,
and **rejected by the pre-registered rule**. It gave the sparse side rows for
49 of 50 questions (from 7) and improved deeper recall (k=10 44 → 46, k=20
46 → 49). At k=3, the cut the LLM sees, it moved one path (38 → 39) against a
required +2, and it pushed q007's declared path from rank 1 to rank 5. A1 and A2
fail. The query was reverted to `plainto_tsquery`. The measurement tooling and
the new sanitising tests stay. Full numbers and the q007 analysis are in ADR-017's
Outcome.

## What was built

In order, with the commit each step landed in (cited by subject; the branch may be
rebase-merged):

1. `docs(adr): ADR-017 planned -- DF-filtered OR for the sparse side`. ADR
   Planned with the rule copied byte-identical from DEFINE, before any code.
2. `feat(retrieval): DF-filtered OR on the sparse side (ADR-017, pre-measurement)`.
   The code that was measured:
   - `retrieval/hybrid_search.py`: `SPARSE_TERMS_CTES` shared by `HYBRID_QUERY` and
     `SPARSE_TERMS_QUERY`, plus `sparse_terms()`
   - `contracts.py`: `SparseTerm`, `SparseTerms`
   - `scripts/retrieval_recall.py`: per-question `sparse_terms`, `has_sparse_rows`,
     `questions_with_sparse_rows`, `--baseline` with a comparability check
   - `scripts/ask.py`: the kept/dropped line (COULD)
   - `sql/99_verify.sql` section 5 mirrored the new query
   - `Makefile`: `make retrieval-recall baseline=FILE`
   - tests: 7 integration tests for the filter, 6 unit tests for the query shape,
     5 contract tests, 8 unit tests for the recall script's comparison logic
3. The measurement (below), then the rollback the DESIGN specified, the Outcome,
   and the documentation (this commit).

**Remaining after the rollback** (net change of the feature on the code):

| File | What stays |
|---|---|
| `scripts/retrieval_recall.py` | `has_sparse_rows`, `questions_with_sparse_rows`, `--baseline`, `comparability_problems`, `baseline_deltas`. It opens one connection for all 50 retrievals instead of one per question |
| `Makefile` | `baseline=` on `retrieval-recall` |
| `tests/unit/test_retrieval_recall.py` | new, 8 tests |
| `tests/integration/test_hybrid_search_postgres.py` | `seed(..., file_of=…)`. The tiebreak test puts both chunks in one file. Two noisy inputs (`:* ( !`, backslash) and a quote/backslash test |
| `retrieval/hybrid_search.py`, `sql/99_verify.sql` | one comment each naming ADR-017 |
| docs | ADR-017 (Rejected, Outcome), ADR index, ADR-003 §B note, README next-steps + Known Gaps, KB `rag/hybrid-retrieval.md` |

## The measurement

Pre-measurement checks, run right before the first recall run:

- ADR-017's rule is byte-identical to DEFINE's: `awk` range extract from both
  files, then `diff`. 28 lines, no difference.
- Index `sdd-kafka-databricks@f1295df9`, `sdd-kafka-snowflake-2@82a2e269`,
  `BAAI/bge-small-en-v1.5`, 149 + 155 chunks. Same as the before-reading.
- `docs/golden-set/evaluation_questions.yml` unchanged since the before-reading's
  commit. `--baseline` also checks declared paths per question and passed.
- `make lint` clean, `make test` 241 passed, 3 skipped (see Verification).

`make retrieval-recall baseline=.claude/dev/reports/retrieval-recall-20260929-190639.json`,
twice (`-20260930-173857.json`, `-173912.json`; `results` and `summary` equal):

```
  A1  k=3 found:   38 -> 39 /57  (+1)
  A2  top-3 paths lost: 1
        q007  sdd-kafka-snowflake-2/docs/adr/0025_bronze_is_append_only.md
  A3  k=10 found:  44 -> 46 /57
      k=20 found:  46 -> 49 /57
  A4  questions with sparse rows: 7 -> 49 /50
```

Rule: A1 fails (needs ≥ 40), A2 fails (needs 0). **Rejected.**

After the rollback, the same command printed `38 -> 38`, `lost: 0`, `44 -> 44`,
`46 -> 46`, `7 -> 7` (`-20260930-174033.json`). The revert restores the
before-reading exactly.

## What deviated from design

- **`SPARSE_TERMS_QUERY` on an empty index lists the query's terms** (df 0, not
  kept), not an empty list as the first draft of the test assumed. The code was
  right and the test expectation was wrong. The test was corrected to assert that
  behaviour. Removed with the rollback.
- **The queries are composed on one line each with `# nosec B608`.** Bandit
  flagged the multi-line concatenation of module constants as a possible SQL
  injection (Medium, Low confidence). No user text is concatenated: it enters as
  `%(query_text)s`. The repo's existing convention (`writer.py`) is a `nosec` on
  the composing line. Removed with the rollback.
- **`sql/99_verify.sql`'s EXPLAIN was run after the recall measurement, not
  before.** Its question is q002, a golden question. Running it first would have
  been a partial look at the candidate before the rule was applied.
- **The recall script's first-draft docstring promised to report a corner case**
  (sparse rows that miss the fused top 20). Nothing could detect it cheaply, so
  DESIGN was corrected before BUILD to say the count undercounts in that case,
  which makes A4 harder to pass.
- **The integration "sanitising" list gained two inputs**, as DESIGN said. The
  existing cases are unchanged.

## RAGAS delta

**Not measured. `make eval` does not produce scores yet.** Run on 2026-09-30, it
prints `scripts/run_evaluation.py — not yet implemented (BUILD phase pending)`.
Generation does not exist, and no Anthropic key is configured. No number is
written here, per AGENTS.md ("Never invent RAGAS scores").

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Faithfulness | pending | pending | — |
| Context Precision | pending | pending | — |
| Answer Relevance | pending | pending | — |
| Context Recall | pending | pending | — |
| Fallback rate | pending | pending | — |

Source recall at k (ADR-014) stands in. It is the table above. After the rollback,
the shipped code's retrieval is identical to the before-reading (38/44/46).

## Query plan of the measured (rejected) query

`make verify-indexes`, section 5, q002, run after the recall measurement and
before the rollback. `sparse_query` is evaluated once (InitPlan 3), the
per-lexeme document-frequency counts use the GIN index (11 loops, one per
distinct lexeme), and execution took 5.17 ms. After the rollback, section 5 is
back to the `plainto_tsquery` query, whose baseline is unchanged from before this
feature.

```
                                                                                   QUERY PLAN                                                                                   
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 Limit  (cost=4131.61..4131.66 rows=20 width=40) (actual time=4.931..4.941 rows=20 loops=1)
   Buffers: shared hit=2405
   CTE candidates
     ->  Seq Scan on chunks c_1  (cost=4021.40..4078.72 rows=304 width=20) (actual time=0.973..4.602 rows=304 loops=1)
           Filter: (collection = ANY ('{decisions,architecture}'::text[]))
           Buffers: shared hit=2396
           InitPlan 1 (returns $0)
             ->  Limit  (cost=0.15..0.38 rows=1 width=151) (actual time=0.007..0.008 rows=1 loops=1)
                   Buffers: shared hit=2
                   ->  Index Scan using chunks_pkey on chunks  (cost=0.15..70.96 rows=304 width=151) (actual time=0.007..0.008 rows=1 loops=1)
                         Buffers: shared hit=2
           InitPlan 3 (returns $2)
             ->  Aggregate  (cost=4021.01..4021.02 rows=1 width=32) (actual time=0.493..0.497 rows=1 loops=1)
                   Buffers: shared hit=281
                   ->  Sort  (cost=4020.67..4020.84 rows=67 width=32) (actual time=0.487..0.491 rows=9 loops=1)
                         Sort Key: term.term
                         Sort Method: quicksort  Memory: 25kB
                         Buffers: shared hit=281
                         ->  Nested Loop  (cost=73.34..4018.64 rows=67 width=32) (actual time=0.331..0.472 rows=9 loops=1)
                               Join Filter: ((SubPlan 2) <= (max((count(*)))))
                               Rows Removed by Join Filter: 2
                               Buffers: shared hit=281
                               ->  Aggregate  (cost=58.36..58.37 rows=1 width=8) (actual time=0.242..0.243 rows=1 loops=1)
                                     Buffers: shared hit=52
                                     ->  HashAggregate  (cost=57.32..57.78 rows=46 width=59) (actual time=0.236..0.239 rows=47 loops=1)
                                           Group Key: chunks_2.source_project, chunks_2.source_path
                                           Batches: 1  Memory Usage: 24kB
                                           Buffers: shared hit=52
                                           ->  Seq Scan on chunks chunks_2  (cost=0.00..55.04 rows=304 width=51) (actual time=0.001..0.047 rows=304 loops=1)
                                                 Buffers: shared hit=52
                               ->  HashAggregate  (cost=14.99..16.99 rows=200 width=32) (actual time=0.051..0.053 rows=11 loops=1)
                                     Group Key: term.term
                                     Batches: 1  Memory Usage: 40kB
                                     ->  Function Scan on regexp_split_to_table term  (cost=0.00..12.50 rows=995 width=32) (actual time=0.046..0.047 rows=11 loops=1)
                                           Filter: (term <> ''::text)
                               SubPlan 2
                                 ->  Aggregate  (cost=19.69..19.70 rows=1 width=8) (actual time=0.015..0.015 rows=1 loops=11)
                                       Buffers: shared hit=229
                                       ->  Bitmap Heap Scan on chunks chunks_1  (cost=12.83..19.69 rows=2 width=0) (actual time=0.008..0.013 rows=40 loops=11)
                                             Recheck Cond: (content_tsv @@ (term.term)::tsquery)
                                             Heap Blocks: exact=196
                                             Buffers: shared hit=229
                                             ->  Bitmap Index Scan on idx_chunks_content_tsv_gin  (cost=0.00..12.83 rows=2 width=0) (actual time=0.005..0.005 rows=40 loops=11)
                                                   Index Cond: (content_tsv @@ (term.term)::tsquery)
                                                   Buffers: shared hit=33
   ->  Sort  (cost=52.89..53.65 rows=304 width=40) (actual time=4.930..4.933 rows=20 loops=1)
         Sort Key: ((COALESCE((1.0 / ((60 + d.dense_rank))::numeric), '0'::numeric) + COALESCE((1.0 / ((60 + s.sparse_rank))::numeric), '0'::numeric))) DESC, c.id
         Sort Method: quicksort  Memory: 27kB
         Buffers: shared hit=2405
         ->  Hash Left Join  (cost=30.52..44.80 rows=304 width=40) (actual time=4.836..4.895 rows=32 loops=1)
               Hash Cond: (c.id = s.id)
               Filter: ((d.dense_rank IS NOT NULL) OR (s.sparse_rank IS NOT NULL))
               Rows Removed by Filter: 272
               Buffers: shared hit=2399
               ->  Hash Left Join  (cost=19.47..26.99 rows=304 width=16) (actual time=4.779..4.815 rows=304 loops=1)
                     Hash Cond: (c.id = d.id)
                     Buffers: shared hit=2396
                     ->  CTE Scan on candidates c  (cost=0.00..6.08 rows=304 width=8) (actual time=0.975..0.986 rows=304 loops=1)
                           Buffers: shared hit=290
                     ->  Hash  (cost=19.22..19.22 rows=20 width=16) (actual time=3.783..3.784 rows=20 loops=1)
                           Buckets: 1024  Batches: 1  Memory Usage: 9kB
                           Buffers: shared hit=2106
                           ->  Subquery Scan on d  (cost=18.62..19.22 rows=20 width=16) (actual time=3.773..3.780 rows=20 loops=1)
                                 Buffers: shared hit=2106
                                 ->  Limit  (cost=18.62..19.02 rows=20 width=24) (actual time=3.773..3.778 rows=20 loops=1)
                                       Buffers: shared hit=2106
                                       ->  WindowAgg  (cost=18.62..24.70 rows=304 width=24) (actual time=3.771..3.775 rows=20 loops=1)
                                             Buffers: shared hit=2106
                                             ->  Sort  (cost=18.62..19.38 rows=304 width=16) (actual time=3.768..3.769 rows=20 loops=1)
                                                   Sort Key: candidates.dense_dist, candidates.id
                                                   Sort Method: quicksort  Memory: 36kB
                                                   Buffers: shared hit=2106
                                                   ->  CTE Scan on candidates  (cost=0.00..6.08 rows=304 width=16) (actual time=0.001..3.707 rows=304 loops=1)
                                                         Buffers: shared hit=2106
               ->  Hash  (cost=10.80..10.80 rows=20 width=16) (actual time=0.049..0.050 rows=20 loops=1)
                     Buckets: 1024  Batches: 1  Memory Usage: 9kB
                     Buffers: shared hit=3
                     ->  Subquery Scan on s  (cost=10.20..10.80 rows=20 width=16) (actual time=0.043..0.048 rows=20 loops=1)
                           Buffers: shared hit=3
                           ->  Limit  (cost=10.20..10.60 rows=20 width=20) (actual time=0.042..0.046 rows=20 loops=1)
                                 Buffers: shared hit=3
                                 ->  WindowAgg  (cost=10.20..12.22 rows=101 width=20) (actual time=0.042..0.045 rows=20 loops=1)
                                       Buffers: shared hit=3
                                       ->  Sort  (cost=10.20..10.45 rows=101 width=12) (actual time=0.040..0.041 rows=20 loops=1)
                                             Sort Key: candidates_1.sparse_score DESC, candidates_1.id
                                             Sort Method: quicksort  Memory: 30kB
                                             Buffers: shared hit=3
                                             ->  CTE Scan on candidates candidates_1  (cost=0.00..6.84 rows=101 width=12) (actual time=0.001..0.014 rows=131 loops=1)
                                                   Filter: (sparse_score > '0'::double precision)
                                                   Rows Removed by Filter: 173
 Planning:
   Buffers: shared hit=104
 Planning Time: 1.354 ms
 Execution Time: 5.174 ms
```

## Known gaps at merge time

- **The sparse side is still inert for question-shaped input** (7/50). Next: the
  honest dense-only ADR the author pre-agreed to.
- **3 integration tests skip** because `/tmp/dpr-corpus-*` does not exist
  (`tests/integration/test_golden_set_files.py`). This predates the feature and
  does not touch retrieval. `make fetch-corpus` restores them.
- **The README's Known Gaps says "The golden set holds 5 of 50 questions".**
  It holds 50. This predates the feature and was not changed here. Flagged for
  the author.

## Verification

- [x] `make lint` clean (after the rollback, and on the measured commit)
- [x] `make test` green: 223 passed, 3 skipped after the rollback (241 passed on
      the measured commit)
- [ ] `make eval` results attached: **not possible**, `run_evaluation.py` is a
      stub (see RAGAS delta)
- [x] `make verify-indexes` shows expected query plans: filtered query above,
      plus sections 4 and 6 unchanged
- [x] Two identical recall runs. The rule was applied once, to the first
- [x] Revert reproduces the before-reading exactly
