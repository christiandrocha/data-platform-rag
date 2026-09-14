# DESIGN: {Feature Name}

> Link back to DEFINE.md

## Metadata

| Field | Value |
|-------|-------|
| Feature | {feature-slug} |
| Depends on | DEFINE.md (link) |
| Status | Draft / Reviewed / Approved |
| ADR needed | Yes / No — if yes, link ADR-XXX |

## Architecture overview

Diagram or prose (or both). Answer: what components change, what stays, how they interact.

## Data contracts

Schemas of any new tables, message payloads, or file formats introduced.

## Interfaces

- Public API changes (function signatures, HTTP endpoints, CLI flags)
- Config additions (env vars, YAML keys)

## Retrieval and RAG-specific concerns (if applicable)

- [ ] Does this affect chunking? Which sources?
- [ ] Does this touch the HNSW index? Reindex needed?
- [ ] Does this change the query pattern? EXPLAIN ANALYZE baseline updated?
- [ ] Does this change RAGAS metrics? Regression test needed?

## Alternatives considered

- Option A — pros, cons, why rejected
- Option B — pros, cons, why rejected

## Test plan

- Unit tests: what functions
- Integration tests: what pipelines
- Manual verification: what queries against local db

## Rollout plan

- Migration order (if schema change)
- Feature flag (if user-visible)
- Rollback plan (what breaks if we revert)

## Open questions

- [ ] Question 1
