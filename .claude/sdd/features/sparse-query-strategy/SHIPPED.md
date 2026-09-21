# SHIPPED: The tsquery function — making the sparse side exist

## Metadata

| Field | Value |
|-------|-------|
| Feature | sparse-query-strategy |
| Shipped date | 2026-09-21 |
| PR | [#6](https://github.com/christiandrocha/data-platform-rag/pull/6), merged by rebase |
| Deploy | **none exists.** `ui/app.py` is a TODO stub and no Streamlit Cloud URL has ever been published |
| ADR | [ADR-015](../../../../docs/adr/ADR-015-or-joined-lexemes-for-the-sparse-side.md) — **Rejected**; pointer added to [ADR-003](../../../../docs/adr/ADR-003-hybrid-retrieval-rrf.md) Amendment 1 §B |

## What shipped, and what did not

**The feature this DEFINE asked for did not ship.** Its goal was a sparse side
that votes for question-shaped input. The fix was built, measured, and rejected
by a rule written before the measurement. Retrieval behaves as it did before
this feature, which the recall artifact proves ranking for ranking.

What shipped is the evidence, and one correction found while producing it:

- ADR-015, Rejected in place, with the numbers and each of its predictions
  checked against them.
- Ties in both ranked lists break by `id`. It changes nothing today; it keeps a
  rank from changing after a reindex when the corpus has not.
- `sql/99_verify.sql` and the KB now describe the query that actually runs.
- Every recall artifact names the commit it was measured against.

## What users see

Nothing. There is no UI and no generation. The curator sees the same
`make ask` and `make retrieval-recall` output as before, plus the snapshot SHAs
at the top of the recall report.

## What we learned

**A populated sparse side is not a useful one.** OR-joining took the sparse side
from rows for 1 of 5 questions to 5 of 5, and recall did not move. With an equal
ballot and no weight, the sparse vote for a wrong ADR was as strong as the one for
the right ADR, and on q001 they cancelled into an exact tie.

**Writing the rule before measuring worked, and so did its gap.** The rule
had no row for "nothing moved", and the reading landed there. What decided the
outcome was a separate, concrete DEFINE criterion (q001 stays at rank 1). A
criterion on a named case caught what an aggregate threshold could not.

**The prediction that motivated the feature was the one that failed.** ADR-015
expected the gain to concentrate in q002. It moved one place, 7 → 6. The
predictions about what would *not* improve (q004) and what would get worse (q005)
were right. Pessimistic predictions held up better than the optimistic one.

## Retrospective for the log

- **Look for determinism bugs where the data is empty.** The missing tiebreak
  existed since the query was written. It was invisible because the sparse list
  was empty, and it surfaced the moment the list was populated.
- **A verify script can check a query nobody runs.** `99_verify.sql` §5 ran a
  keyword query with an `@@` predicate the real query never had. It ran clean
  while measuring nothing real. The fix mirrors the real query, and the mirror is
  itself a drift risk (recorded as a known gap).
- **An unmeasured claim reached an approved ADR draft.** "Shared by most chunks"
  was written without `ts_stat`, approved, then measured as 31 % and corrected
  before commit. Measure first, even inside a sentence that only explains.
- **Next decision:** reranker (ADR-005) before term filtering (ADR-015
  Alternative 2)? Recall at k=20 is already 5/6 dense-only, and a cross-encoder
  re-sorts exactly the top where OR tied. Recorded, unmeasured.
