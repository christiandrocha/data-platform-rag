# ADR Index — data-platform-rag

Chronological register of architecture decisions taken in this project.
Format follows the convention used in `sdd-kafka-snowflake-2` and `sdd-kafka-databricks`.
Reversals are documented in-place; superseded ADRs stay in the record.

| ID | Title | Status | Date |
|----|-------|--------|------|
| ADR-001 | Postgres + pgvector over dedicated vector databases | Accepted | 2026-09-10 |
| ADR-002 | Two logical collections in one physical table | Accepted | 2026-09-10 |
| ADR-003 | Hybrid retrieval — dense + sparse via reciprocal rank fusion | Accepted | 2026-09-10 |
| ADR-004 | Embedding model selection and HNSW parameter tuning | Planned | — |
| ADR-005 | Cross-encoder reranking of the RRF top 20 | Planned | — |
| ADR-006 | Out-of-scope fallback message design | Accepted | 2026-09-10 |
| ADR-007 | Chunking strategy per source type | Accepted | 2026-09-14 |
| ADR-008 | RAGAS in CI with regression threshold | Planned | — |
| ADR-009 | Langfuse for LLM observability | Accepted | 2026-09-10 |
| ADR-010 | Pydantic v2 as the contract language | Accepted | 2026-09-10 |
| ADR-011 | Golden set curation methodology | Accepted | 2026-09-14 |
| ADR-012 | Corpus snapshot as a shared, provenance-bearing artifact | Accepted | 2026-09-17 |
| ADR-013 | Corpus provenance in Postgres, and replace-by-scope indexing | Accepted | 2026-09-18 |
| ADR-014 | Source recall at k as the retrieval metric, before RAGAS exists | Accepted | 2026-09-18 |
| ADR-015 | OR-joined lexemes for the sparse side of hybrid retrieval | Rejected | 2026-09-21 |

**Legend**: Accepted (implemented as decided) · Planned (decision pending BUILD phase) · Rejected (measured and not adopted; kept as record) · Superseded · Resolved.
