# SHIPPED: Retrieval — the executor, and a way to run a question

## Metadata

| Field | Value |
|-------|-------|
| Feature | retrieval |
| Shipped date | 2026-09-21 |
| PR | [#2](https://github.com/christiandrocha/data-platform-rag/pull/2), merged by rebase |
| Deploy | **none exists.** `ui/app.py` is a TODO stub and no Streamlit Cloud URL has ever been published |
| ADR | [ADR-014](../../../../docs/adr/ADR-014-source-recall-before-ragas.md), plus [ADR-003 Amendment 1](../../../../docs/adr/ADR-003-hybrid-retrieval-rrf.md) |

## What users see

Still no end user — there is no UI and no generation. What exists is the
curator's instrument: `make ask q="..."` returns ranked chunks with their
citations, no LLM involved, and `make retrieval-recall` measures source recall at
k over the golden set.

The first baseline, on 4 in-scope questions and **6 declared source paths**:

```
k=3    3/6   (50%)
k=10   5/6   (83%)
k=20   5/6   (83%)
```

The denominator is six. One path moving is 17 percentage points, and ADR-014's
own Consequences forbid quoting these numbers without saying so.

## What we learned

**The sparse half of hybrid retrieval has never returned a row for a real
question.** `plainto_tsquery` conjoins every term, so a natural-language question
demands one chunk contain all of them: 0 chunks for four of five golden-set
questions. This project's "hybrid" retrieval has been dense-only since the query
was written. The fusion arithmetic is correct; the second list is simply never
populated. Recorded in ADR-003 Amendment 1 §B and deliberately not fixed here —
changing it is a retrieval-strategy decision that gets its own ADR. That decision
is open as `sparse-query-strategy`.

**`fallback_threshold` cannot live on an RRF score.** RRF ranks and then discards
magnitude, so any non-empty result tops out at `1/(60+1) = 0.0164`. The
out-of-scope question scores identically to three of the four in-scope ones.
`settings.fallback_threshold` is 0.35, so against an RRF score it would fire on
100% of queries. The threshold has to operate on the reranker score, which
ADR-005 and ADR-006 both need on record before the fallback is built.

Both findings are worth more than the code this feature shipped.

## Retrospective for the log

- **The query had never been executed.** It used asyncpg placeholders in a
  psycopg project, returned two of the five fields its contract required, and
  ignored the `collections` argument it accepted. A unit test pinned the
  unexecutable form, so the suite was green the whole time.
- **A test can pin a defect as if it were a contract.** `test_hybrid_search_query.py`
  asserted `"embedding <=> $1::vector" in HYBRID_QUERY`. It was corrected, not
  deleted.
- **Measure before the metric that needs generation exists.** RAGAS cannot run
  without answers; source recall at k can, and it produced two findings on its
  first reading. ADR-014 exists because of this.
