# ADR-010 — Pydantic v2 as the contract language for all inter-module boundaries

**Status**: Accepted
**Date**: 2026-09-10

## Context

`data-platform-rag` has multiple modules that exchange structured data — chunks
between indexer and retrieval, retrieval results between hybrid_search and
reranker, LLM output between the API client and consumer code, RAGAS results
between evaluation and reporting, config across the whole application.

Without a contract discipline, these become `dict[str, Any]` or ad-hoc
dataclasses that drift over time — silent schema mismatches, missing fields
discovered at runtime, no type-safety in IDEs.

## Decision

Use **pydantic v2** as the contract language for every inter-module boundary
in the project:

- All shared data structures live in `data_platform_rag/contracts.py`
- Config uses `pydantic-settings` with a singleton pattern via `@lru_cache`,
  no `os.getenv` in application code
- LLM structured output is validated via pydantic `model_validate_json` with
  a one-shot repair retry on `ValidationError`, and a safe default on repair
  failure
- Models are frozen where possible (`ConfigDict(frozen=True)`) to enforce
  value-object semantics
- `dict[str, Any]` in public function signatures is forbidden — exceptions
  require an ADR

## Consequences

**Positive**:
- Type-safe access across module boundaries. IDE autocomplete and static
  type checkers surface mismatches before runtime.
- Config errors fail at startup, not deep in the pipeline.
- LLM structured output has a repair path built-in, not scattered.
- Serialization (`model_dump_json`) is native — Langfuse trace metadata and
  API responses use the same contracts as internal code.
- Every new module boundary starts with the model definition, forcing
  clarity about what crosses the wire.

**Negative / accepted trade-offs**:
- Adds a runtime validation overhead. Negligible at this scale (single-digit
  microseconds per model instance).
- pydantic v2 error messages can be verbose. Mitigation: log field-path
  context, don't just re-raise as generic ValueError.
- Refactors that change a model shape ripple through every consumer. This
  is a feature — silent drift is worse than explicit refactor pain.

## Alternatives considered

- **`dataclasses` from stdlib**: lighter, no runtime validation. Rejected
  because config and LLM output validation are core requirements.
- **`attrs` + `cattrs`**: same power as pydantic v2, less ubiquitous in the
  LLM/RAG ecosystem. Rejected for team-familiarity reasons.
- **TypedDict for static-only typing, no runtime validation**: cheapest,
  but silently accepts wrong types at runtime. Rejected for boundaries that
  cross the network (LLM output, config from environment).

## Related

- `.claude/kb/pydantic/models.md` — the actual models in `contracts.py`
- `.claude/kb/pydantic/config-pattern.md` — the pydantic-settings singleton
- `.claude/kb/pydantic/llm-output-validation.md` — repair pattern for LLM JSON
