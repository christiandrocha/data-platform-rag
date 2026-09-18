# ADR-003 — Hybrid retrieval via reciprocal rank fusion

**Status**: Accepted
**Date**: 2026-09-10

## Context

Dense embeddings excel at semantic similarity ("What is Christian's approach
to CDC?" retrieves ADRs about Debezium even if the word CDC isn't in them).
Sparse retrieval (BM25-like, using PostgreSQL tsvector) excels at exact-term
matches ("ADR-0019" retrieves the exact ADR file). Neither alone is enough
for a technical corpus where users mix conceptual questions and specific
identifiers.

The Rimini Street AI Data Engineer III JD explicitly lists "hybrid retrieval
approaches combining dense embeddings, sparse search (BM25), and metadata
filtering" as a required capability.

## Decision

Implement hybrid retrieval combining pgvector cosine similarity and PostgreSQL
`ts_rank_cd` scores via **reciprocal rank fusion (RRF)** with rank constant
k=60 (Cormack et al., 2009). Metadata pre-filtering happens before both.

RRF formula for each chunk:
```
score = 1/(k + dense_rank) + 1/(k + sparse_rank)
```

Both ranks are computed independently over the same pre-filtered candidate
set (top 20 from each). Chunks that appear in only one list still contribute
their score (the missing side counts as rank infinity → contributes zero).

## Consequences

**Positive**:
- No score normalization needed — RRF operates on ranks, not raw scores.
  Dense cosine similarity and BM25 scores have incomparable ranges;
  normalizing them requires calibration that shifts with the corpus.
- Robust to sparse-only or dense-only queries. Query "ADR-0019" gets a
  perfect sparse hit; conceptual query gets dense hits.
- Simple to implement in one SQL query with CTEs.

**Negative / accepted trade-offs**:
- RRF ignores the *magnitude* of similarity. A chunk with cosine 0.95 gets
  the same weight as a chunk with cosine 0.51 if both are rank 1 in their
  respective lists. Learned fusion (linear combination with tuned weights)
  could outperform RRF at the cost of needing labeled training data.
- k=60 is the paper's canonical value. Tuning against the golden set is a
  future exercise (candidate for a new ADR if RAGAS shows lift).

## Alternatives considered

- **Dense only**: simplest, but loses exact-term precision. Golden-set
  queries with ADR IDs would degrade.
- **Sparse only**: loses semantic paraphrase capability.
- **Learned linear fusion**: `α * dense + (1-α) * sparse` with α tuned on
  golden set. More powerful but needs enough labeled data — deferred until
  the golden set exceeds 100 questions.
- **Weaviate-style hybrid with alpha parameter**: essentially learned linear
  fusion with a runtime knob. Same deferred rationale.

## Verification

`sql/99_verify.sql` includes an EXPLAIN ANALYZE baseline for the hybrid
query. Query plan must show both `idx_chunks_embedding_hnsw` and
`idx_chunks_content_tsv_gin` in use.

---

## Amendment 1 — 2026-09-18, corrected by first execution

The query implementing this ADR had never been run. Executing it for the first
time, during the `retrieval` feature, exposed one arithmetic drift from what this
ADR specifies. Recorded here rather than by superseding, following the ADR-007
Amendment 1 precedent.

### A. The missing side contributed a sentinel, not zero

**This ADR states** that a chunk appearing in only one ranked list has the
missing side count "as rank infinity → contributes zero".

**The implementation used** `COALESCE(dense_rank, 999)`, so a missing side
contributed `1 / (60 + 999) = 0.000944`. A rank-1 contribution is
`1 / (60 + 1) = 0.016393`, so the sentinel was worth **5.8 % of a top rank** —
a constant bonus applied to every one-sided match, tilting them as a group
against chunks that genuinely appeared in both lists.

**Corrected to** `COALESCE(1.0 / (60 + rank), 0)` per side: the coalesce now
wraps the contribution rather than the rank, so an absent side contributes
exactly zero, as this ADR always said it should. `999` is gone; it read like a
limit and behaved like a bias.

Asserted in `tests/integration/test_hybrid_search_postgres.py`, which computes
the expected fused score by hand for a chunk ranked by the sparse side alone.

### B. Not amended, but recorded: the sparse side is inert for real questions

Measured against the golden set on the same day, and **left as-is deliberately**,
because changing it is a retrieval-strategy decision that needs its own ADR
rather than an amendment to this one.

`plainto_tsquery` conjoins every term. For a natural-language question it
therefore demands that one chunk contain all of them:

```
plainto_tsquery('english', 'Why did the Snowflake project choose Snowpipe
Streaming over the classic file-based Snowpipe?')
  → 'snowflak' & 'project' & 'choos' & 'snowpip' & 'stream'
    & 'classic' & 'file-bas' & 'file' & 'base' & 'snowpip'
  → 0 chunks
```

Across the five golden-set questions, the sparse side matched **0 chunks for
four of them**, and 2 for the fifth. `websearch_to_tsquery` behaves identically.
OR-joining the lexemes matches 158–211 of 304 chunks instead.

The consequence is that this project's "hybrid" retrieval is, in practice,
**dense-only for question-shaped input**, and has been since the query was
written. The fusion machinery is correct and the sparse half is simply never
populated. See the `retrieval` BUILD_REPORT for the measurement.
