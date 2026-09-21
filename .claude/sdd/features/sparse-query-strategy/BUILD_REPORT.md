# BUILD REPORT: The tsquery function — making the sparse side exist

## Metadata

| Field | Value |
|-------|-------|
| Feature | sparse-query-strategy |
| DEFINE | [DEFINE.md](DEFINE.md) |
| DESIGN | [DESIGN.md](DESIGN.md) |
| ADR | [ADR-015](../../../../docs/adr/ADR-015-or-joined-lexemes-for-the-sparse-side.md) — **Rejected** |
| Start date | 2026-09-21 |
| End date | 2026-09-21 |
| PR | [#6](https://github.com/christiandrocha/data-platform-rag/pull/6) |

## Outcome in one paragraph

The OR-joined tsquery was built, tested and measured, and **the measurement
rejected it**. The sparse side went from returning rows for 1 of 5 golden
questions to 5 of 5, and source recall did not move at any k. q001's declared ADR
lost rank 1 to an exact tie with a wrong ADR, which fails a DEFINE criterion.
The OR expression is reverted. Two things found along the way stay: a
tie-breaking fix in both ranked lists, and tests that guard the tsquery's
sanitising. After the revert, `make retrieval-recall` reproduces the
before-artifact exactly.

## What was built (and what remains after the revert)

| File | Change | Status |
|---|---|---|
| `data_platform_rag/retrieval/hybrid_search.py` | OR rewrite of the tsquery | **reverted** |
| same | `id ASC` tiebreak in both `ROW_NUMBER()` windows and their `ORDER BY` | **kept** |
| `tests/unit/test_hybrid_search_query.py` | 3 tests; the OR guard removed on revert | 2 kept |
| `tests/integration/test_hybrid_search_postgres.py` | 11 tests; 3 OR-only removed on revert | 8 kept |
| `sql/99_verify.sql` §5 | Replaced a keyword query that never matched the real one with a mirror of `HYBRID_QUERY` | **kept**, on AND |
| `.claude/kb/rag/hybrid-retrieval.md` | Query copy had asyncpg `$1`, the `999` sentinel and half the columns — stale since before this feature | **kept**, on AND |
| `scripts/retrieval_recall.py` | Artifact records the indexed snapshot (commit SHA, embedding model) | **kept** |
| `docs/adr/ADR-015-…md` | Status Planned → Rejected, Outcome section added in place | — |
| `docs/adr/ADR-003-…md` | One line under Amendment 1 §B pointing to ADR-015 | — |

`make test`: 172 → 186 with OR → **182** after the revert.

## What deviated from design

- **Tie-breaking added to both ranked lists.** DESIGN said "one expression
  changes" and assumed `ORDER BY rrf_score DESC, c.id ASC` made ties
  deterministic. It does not: `ROW_NUMBER()` over a tied key assigns ranks in heap
  order one CTE earlier, so a rank could change after a reindex with no change to
  the corpus. A test that rewrites a row to the end of the heap **failed without
  the fix (`assert 2 == 1`)** and passes with it. Approved before applying.
- **The "tsquery contains `|` and no `&`" test could not be DB-free**, as DEFINE
  asked: the tsquery is produced by Postgres. It became an integration test, and
  was removed with the revert.
- **DESIGN's premise about `sql/99_verify.sql` was wrong.** It said the file
  recorded `rows=0`; that plan lived in the `retrieval` BUILD_REPORT. Section 5 ran
  a keyword query with an `@@` predicate the real query does not have, under a
  comment claiming GIN usage the real query never gets. Rewritten to mirror
  `HYBRID_QUERY`.
- **The KB copy was stale beyond this feature** (asyncpg placeholders, `999`
  sentinel, missing contract columns). Realigned in the same pass.
- **DEFINE's acceptance "both JSONs name the same snapshot SHA" could not be met
  for the before-artifact**, which predates the field. Proven instead by
  `corpus_snapshot` in the database: `f1295df9` / `82a2e269`, indexed
  2026-09-18, before either reading. Every artifact from now on carries it.
- **A false claim was written into ADR-015 and corrected before commit.** The
  first Outcome draft said `project`, `snowflak` and `databrick` were "shared by
  most chunks". Measured with `ts_stat`: the broadest is `snowflak` at 31 %, and
  `databrick` is not a q001 lexeme at all. Corrected to the measured numbers.

## Measurement

Same snapshot throughout. Before: `retrieval-recall-20260921-142654.json`. OR:
`-162458` and `-162524` (identical). After revert: `-163500` (identical to before,
summary and every ranking).

| | before | with OR | after revert |
|---|---|---|---|
| questions with sparse rows | 1/5 | 5/5 | 1/5 |
| source recall k=3 | 3/6 | 3/6 | 3/6 |
| source recall k=10 | 5/6 | 5/6 | 5/6 |
| source recall k=20 | 5/6 | 5/6 | 5/6 |
| q001 declared path rank | 1 | **2** | 1 |
| q005 top fused score | 0.01639 | 0.02964 | 0.01639 |

Per-question ranks and the checked predictions are in ADR-015's Outcome, not
repeated here.

### DEFINE success criteria, with OR

- [x] Sparse rows for 5/5 golden questions
- [x] Source recall k=3 ≥ 3/6 (3/6)
- [x] Source recall k=10 and k=20 ≥ 5/6 (5/6)
- [ ] **q001's declared path stays at rank 1 — failed, rank 2 on an exact tie**
- [x] Two consecutive runs identical
- [x] ≥ 6 new tests (14)

### EXPLAIN ANALYZE — the real `HYBRID_QUERY`, q002, with OR

Run from Python against the constant itself, not the `99_verify.sql` mirror.

```
Limit (actual time=6.369..6.373 rows=20 loops=1)
  CTE candidates
    ->  Seq Scan on chunks (actual time=0.452..5.747 rows=304 loops=1)
  ...
        ->  Hash Left Join (actual time=6.242..6.318 rows=28 loops=1)
              Rows Removed by Filter: 276
              ...
                    ->  Subquery Scan on s (actual time=0.079..0.084 rows=20 loops=1)
                          ...  Sort Key: candidates_1.sparse_score DESC, candidates_1.id
                               ->  CTE Scan on candidates candidates_1 (rows=179 loops=1)
                                     Filter: (sparse_score > '0'::double precision)
                                     Rows Removed by Filter: 125
Execution Time: 6.602 ms
```

After revert, `make verify-indexes` §5 reports `Subquery Scan on s … rows=0`,
`Rows Removed by Filter: 304` — the pre-feature state.

## RAGAS delta

**Not applicable, and no number is written.** RAGAS grades generated answers,
and no generation exists. The metric standing in for it is source recall at k
(ADR-014), and its delta is above: zero at every k with OR, and exactly zero
after the revert.

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Faithfulness | pending | pending | — |
| Context Precision | pending | pending | — |
| Answer Relevance | pending | pending | — |
| Context Recall | pending | pending | — |
| Fallback rate | pending | pending | — |

`make eval` not run: `scripts/run_evaluation.py` is a stub.

## Known gaps at merge time

- **The sparse side is still inert for question-shaped input.** This feature
  confirmed the problem and rejected one fix. It did not solve it.
- **ADR-015's decision rule had a hole**: no row for "flat at every k". It did not
  decide this outcome (the q001 criterion did), but the next rule must cover it.
- **`sql/99_verify.sql` §5 is a hand-written copy of `HYBRID_QUERY`** and can
  drift from it. A script that EXPLAINs the constant itself would remove the copy.
- **The tiebreak changes nothing today**, proven by the identical recall
  artifact. It protects future reindexes, not current numbers.
- **Open question for the next feature: reranker (ADR-005) before term filtering
  (ADR-015 Alternative 2)?** Recall at k=20 — what a reranker receives — is
  already 5/6 dense-only, and the ordering at the top, where OR produced the q001
  tie, is exactly what a cross-encoder redoes. If ADR-005 fixes the top-3
  ordering, the sparse side stops being urgent. Unmeasured; recorded, not decided.

## Verification

- [x] `make lint` — ruff and bandit clean; yamllint reports pre-existing errors in
      `evaluation_questions.yml` (line length) and `corpus_inventory.yml` (final
      newline), files this feature did not touch
- [x] `make test` — 182 passed
- [ ] `make eval` — not applicable, no generation exists
- [x] `make verify-indexes` — runs clean; §5 shows the expected pre-feature plan
- [x] `make retrieval-recall` — before, twice with OR, once after revert; artifacts listed above
