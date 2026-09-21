# DESIGN: The tsquery function — making the sparse side exist

> Implements [DEFINE.md](DEFINE.md). Decision recorded in
> [ADR-015](../../../../docs/adr/ADR-015-or-joined-lexemes-for-the-sparse-side.md).

## Metadata

| Field | Value |
|-------|-------|
| Feature | sparse-query-strategy |
| Depends on | [DEFINE.md](DEFINE.md) — Clarity Score 14/15 |
| Status | Draft |
| ADR needed | **Yes** — [ADR-015](../../../../docs/adr/ADR-015-or-joined-lexemes-for-the-sparse-side.md), status Planned, promoted or rejected by BUILD's measurement |

## Architecture overview

One expression changes, in one file. Nothing else moves.

```
retrieval/hybrid_search.py
  HYBRID_QUERY
    candidates CTE
      ts_rank_cd(content_tsv, <TSQUERY>) AS sparse_score     ← here
    sparse_ranked CTE
      WHERE sparse_score > 0                                  ← unchanged, now selective
```

Today `<TSQUERY>` is `plainto_tsquery('english', %(query_text)s)`. It becomes:

```sql
replace(plainto_tsquery('english', %(query_text)s)::text, ' & ', ' | ')::tsquery
```

The expression appears **once**, as a named SQL fragment interpolated into the
query constant at module level — not twice, because `sparse_score` is computed in
the `candidates` CTE and referenced by name afterwards. `build_hybrid_query()`
keeps its current signature and its collection validation.

**Why the rewrite happens in SQL and not in Python.** `plainto_tsquery` performs
the sanitising. Rebuilding the disjunction from Python-side tokens would move
that responsibility into application code and create the injection surface this
project does not currently have. Verified against the live index on 2026-09-21:

| probe input | `plainto_tsquery` output | after rewrite |
|---|---|---|
| `why $$ ':*!&\|() <-> ADR-0029?` | `'adr' & '-0029'` | `'adr' \| '-0029'` |
| `real-time change-data-capture` | `'real-tim' & 'real' & 'time' & …` | same lexemes, `\|` |
| `Christian's opinion on Flink` | `'christian' & 'opinion' & 'flink'` | `'christian' \| 'opinion' \| 'flink'` |
| `the and of is` | *(empty)* | *(empty)* — matches nothing |
| `''` | *(empty)* | *(empty)* — matches nothing |

Operators in the input are stripped by `plainto_tsquery` before the rewrite sees
them, so no lexeme can contain the ` & ` separator the rewrite matches on. The
empty-query cases collapse to an empty `tsquery`, which matches nothing — the
same outcome as today, reached without an error.

## Data contracts

**None change.** `RetrievedChunk` already carries `sparse_score` and
`sparse_rank`, both added during the `retrieval` feature precisely so the two
sides could be told apart. `sparse_rank` stops being `None` for most rows, which
is the observable difference and requires no contract edit.

No new table, no new column, no migration.

## Interfaces

- **Public API**: unchanged. `search()`, `retrieve()` and `build_hybrid_query()`
  keep their signatures.
- **CLI**: unchanged. `make ask` gains no flag; its `sparse` column simply stops
  being empty.
- **Config**: **nothing added.** In particular, no sparse weight — see the open
  question below, which ADR-015 resolves by deciding *not* to add one.

## Retrieval and RAG-specific concerns

- [x] **Chunking** — unaffected. No source type changes, no re-chunk.
- [x] **HNSW index** — untouched. The dense side of the query is not modified and
      **no reindex is needed**. `content_tsv` and its GIN index are also
      unchanged; only the query built against them changes.
- [x] **Query pattern — yes, and the baseline must be updated.**
      `sql/99_verify.sql` records `rows=0` with `Rows Removed by Filter: 304` on
      the sparse subquery as its regression baseline. That baseline becomes wrong
      by design, and BUILD must replace it with the new plan rather than leave a
      file that fails against correct behaviour.
- [x] **RAGAS** — cannot regress, because it does not exist. The metric that can
      regress is source recall at k (ADR-014), and the before-reading is
      `.claude/dev/reports/retrieval-recall-20260921-142654.json`. The decision
      rule in ADR-015 is the regression test.

## Alternatives considered

The four alternatives and their rejections are in
[ADR-015](../../../../docs/adr/ADR-015-or-joined-lexemes-for-the-sparse-side.md):
`websearch_to_tsquery` (measured identical), document-frequency term filtering
(needs a threshold the golden set cannot yet justify), AND-then-OR fallback (two
retrievers behind one entry point, which ADR-014 forbids averaging), and honest
dense-only (reverses a decision on evidence from a broken implementation).

Not repeated here. The ADR is the record.

## Test plan

**Unit** (no database):

1. The query constant contains the `replace(...)` rewrite and no bare
   `plainto_tsquery(` as the `ts_rank_cd` argument — the regression guard for
   someone "simplifying" it back.
2. `build_hybrid_query()` still validates collections, unchanged, both directions.
3. The rewrite is applied **once**, in the `candidates` CTE, and `sparse_score` is
   referenced by name below it.

**Integration** (against the `_test` database, hand-chosen content):

4. A chunk matching **one** of several query terms is ranked by the sparse side
   and contributes exactly `1/(60 + rank)` to the fused score — the ADR-003
   Amendment 1A arithmetic, now exercised on a populated list.
5. A query whose terms are all stopwords returns dense-only results and no error.
6. A query containing `'`, `:`, `!`, `&`, `|` and `<->` produces the same result
   as the same words without them — the sanitising assertion.
7. Ties in `sparse_score` break by `c.id ASC` and two consecutive runs return
   identical orderings. q002's real top two are both `1.5`, so this is not
   hypothetical.
8. The existing empty-index and collection-filter tests still pass unchanged.

**Manual verification** (against the local index, 304 rows):

9. `make ask` with q002's full-sentence question shows a populated `sparse`
   column and non-null `sparse_rank` — the DEFINE acceptance test.
10. `EXPLAIN ANALYZE` shows the sparse subquery returning `rows > 0`.
11. `make retrieval-recall` twice; compare both to the before-artifact.

## Rollout plan

- **Migration order**: none. No schema change.
- **Feature flag**: none, deliberately. A flag would mean shipping two retrievers
  and evaluating neither — the same objection that rejected the AND-then-OR
  alternative. The change is one expression; the flag would cost more than the
  revert.
- **Rollback**: revert the expression. Nothing else depends on it. No data is
  written, no index rebuilt, no contract changed, so a revert restores the
  previous behaviour exactly — including, deliberately, the empty sparse side.
- **Promotion**: BUILD runs the measurement and either promotes ADR-015 to
  Accepted with the numbers, or records the rejection in-place and opens the
  alternative it points to. A rejected ADR is not deleted.

## Open questions

- [x] **Does the sparse side need a weight?** Deferred here by DEFINE; **resolved
      by ADR-015: no weight is introduced.** RRF's two contributions stay
      unweighted because ADR-003 requires weights to be RAGAS-tuned and RAGAS does
      not exist, so any coefficient would be a guess wearing a config field. If
      the measurement shows the sparse side drowning the dense one, the response
      is ADR-015's rejection branch, not an invented number.
- [ ] **Does `sql/99_verify.sql` keep a `rows=0` assertion for the record?**
      BUILD decides: either the old plan is replaced outright, or it is kept
      beside the new one as documented history. Leaning replace — a verify script
      that asserts a defect is how `99_verify.sql` got its two previous bugs.
- [ ] **What shape of input does the product actually receive?** Carried from
      DEFINE, unanswerable without a UI, and recorded so the UI feature inherits
      it. It is the only thing that would reopen the AND-then-OR alternative.
