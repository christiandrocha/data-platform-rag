# ADR-001 — Postgres + pgvector over dedicated vector databases

**Status**: Accepted
**Date**: 2026-09-10
**Decider**: Christian Rocha

## Context

`data-platform-rag` needs a vector store for approximately 150-500 embedded chunks
(ADRs + READMEs + contracts from three source projects). The system will be
publicly hosted on Streamlit Community Cloud with an external Postgres for
persistence. Query load is expected to be low (dozens of queries per day) but
each query must return in under 2 seconds end-to-end.

Two categories of options were considered: dedicated vector databases
(Pinecone, Qdrant, Weaviate, ChromaDB) and general-purpose databases with vector
extensions (PostgreSQL with pgvector, Elasticsearch with dense vector fields).

## Decision

Use PostgreSQL 16 with the `pgvector` 0.7+ extension. HNSW indexes for dense
similarity search. GIN indexes on generated `tsvector` columns for sparse
retrieval. All embeddings, metadata, and query logs live in the same database.

## Consequences

**Positive**:
- Single database dependency. No cross-service latency for metadata filtering.
- Metadata filters (`WHERE collection = 'decisions'`) are trivial SQL, not
  proprietary query DSL.
- Hybrid retrieval (dense + sparse) is native — both use the same table.
- Explicitly matches the requirement in target job specifications
  (e.g. Rimini Street AI Data Engineer III lists pgvector under Required, not
  Preferred). Building on pgvector is not a substitute for the target stack;
  it *is* the target stack.
- Query plans are inspectable with standard `EXPLAIN ANALYZE`. Regression
  baselines can be committed to the repo (`sql/99_verify.sql`).

**Negative / accepted trade-offs**:
- No first-class filtering during HNSW graph traversal — pre-filtering by
  metadata happens either before (via `WHERE` before the ORDER BY) or after
  (top-k then filter, which is wrong at low k). Chose pre-filter with the
  composite index `(collection, source_project)` to make the common case fast.
- HNSW parameters need tuning (see ADR-004). The `pgvector` defaults are a
  reasonable starting point but not optimal.
- Streamlit Community Cloud does not host Postgres — external DB needed.
  Chose Neon (free tier: 3GB, sufficient for this scale) as first candidate.

## Alternatives considered

- **Pinecone**: managed, zero-ops, but adds an external dependency and
  proprietary lock-in. Free tier has meaningful limits. Not the target stack.
- **Qdrant Cloud (free tier)**: powerful and open-source, but adds a second
  database when Postgres would already exist for metadata and logs.
- **ChromaDB in-memory persisted to repo**: was the initial plan (see chat
  log 2026-09-10). Rejected once pgvector became a requirement, not a
  preference, in target roles. ChromaDB has no path to those roles.
- **Elasticsearch with dense_vector**: overkill for 500 chunks, heavy
  operational surface. Would win at 10M+ chunks.

## Notes

This decision is scoped to the current scale (hundreds of chunks). If the corpus
grows past 10k chunks and query latency degrades, revisit — either by tuning
HNSW parameters further, migrating to Qdrant, or partitioning the chunks table.
The ADR must be superseded, not amended silently.
