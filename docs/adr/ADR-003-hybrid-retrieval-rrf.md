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
