# ADR-002 — Two logical collections in one physical table

**Status**: Accepted (revised from initial draft — see Note below)
**Date**: 2026-09-10

## Context

`data-platform-rag` retrieves from two conceptually distinct collections drawn from
the two corpus source repositories:

- `decisions` — the ADRs from both `sdd-kafka-snowflake-2` and `sdd-kafka-databricks`
- `architecture` — READMEs, macros, YAML data contracts, and other technical
  documentation from both source projects

The natural implementation would be two separate tables or two Postgres
schemas. This has cost with no observable benefit at our scale.

## Decision

One physical table `chunks` with a `collection TEXT NOT NULL` column
constrained via CHECK to the two values. Composite index on
`(collection, source_project)` supports the common pre-filter pattern.

## Consequences

**Positive**:
- Query patterns like "search across both collections" become a single
  `WHERE collection IN (...)` — trivial. Separate tables would need UNION ALL.
- Schema migrations touch one table. Adding a future collection means one
  value to the CHECK constraint, not a new table.
- HNSW index is shared. Two separate indexes would double maintenance and
  build time with no retrieval benefit at this scale.

**Negative / accepted trade-offs**:
- The CHECK constraint enforces the two-value invariant. Adding a collection
  requires a migration, not an INSERT. This is intentional — collections are
  architectural, not user-generated.
- Row-level partitioning was considered and rejected. At ~200 rows, partition
  overhead exceeds any benefit.

## Alternatives considered

- **Two physical tables**: cleaner conceptual mapping but forces UNION ALL
  for cross-collection queries, doubles index maintenance.
- **Two Postgres schemas**: same downsides plus permission complexity.
- **Three collections including `methodology` (self-indexed data-platform-rag)**:
  considered in initial draft. Rejected. Indexing this repo's own ADRs
  would create a recursion risk (`data-platform-rag` answering questions about
  itself using its own ADRs about itself) and was not part of the original
  product intent. This project's ADRs live in `docs/adr/` for human readers,
  not as retrievable context.

## Note on revision

This ADR was drafted with three collections (`decisions`, `architecture`,
`methodology`) before the corpus scope was finalized. Corrected to two
collections after explicit user confirmation that the corpus is
`sdd-kafka-snowflake-2` + `sdd-kafka-databricks` only.
