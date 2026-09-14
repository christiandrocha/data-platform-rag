# Pydantic KB — data-platform-rag

Scope: pydantic v2 as the contract language for everything that crosses a
boundary in `data-platform-rag` — config, chunk metadata, retrieval results, LLM
output, RAGAS results, API responses, Langfuse trace metadata.

## Files

- `models.md` — the actual models used in data_platform_rag/contracts.py
- `config-pattern.md` — pydantic-settings for env-based configuration
- `llm-output-validation.md` — validating structured output from Claude

## Design principles

1. **Contracts before code.** Every new inter-module boundary gets a pydantic
   model in `data_platform_rag/contracts.py` BEFORE the code that uses it.
2. **Frozen where possible.** `model_config = ConfigDict(frozen=True)` on
   value objects. Mutable models only where mutation is the point (e.g.
   builder pattern for retrieval pipeline result).
3. **Discriminated unions for polymorphism.** When a field can be one of
   several shapes (intent classification result, chunk source type),
   use discriminated unions with `Literal` types.
4. **No dict[str, Any] as public API.** If you find yourself typing that,
   write the model instead. Any exception needs an ADR.

## Anti-patterns

- Constructing pydantic models with `model_validate({...})` from raw dicts
  when a direct `Model(field=value)` call would work
- Using `.dict()` (v1 API) instead of `.model_dump()`
- Adding `Field(default=lambda: ...)` — use `default_factory` instead
- Catching `ValidationError` and re-raising as generic `ValueError` — lose
  the actionable field-path context
