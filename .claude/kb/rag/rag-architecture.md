# RAG architecture reference — data-platform-rag

## Pipeline stages

```
Query → Dense retrieval (ADR-018), top settings.rerank_top_k → LLM under SYSTEM_PROMPT → answer, or the fallback by rule 3
```

Not built: the intent classifier (default collections stand in for it) and the
reranker (ADR-005 rejected both candidates). There is no score gate: ADR-019
measured that similarity does not separate in-scope from out-of-scope.

**Generation** (`generation/client.py`) is one Claude call: `SYSTEM_PROMPT`,
then a user message of tagged chunks (`CONTEXT_FORMAT_VERSION`) and the
question, at `settings.llm_model`, `settings.llm_temperature` and
`settings.llm_max_tokens`, with no extended thinking. Whether rule 3 sends the
fallback when, and only when, it should is measured by `make fallback-eval`
against ADR-020's rule.

## Design principles

1. **Grounded or silent**: never generate answers without cited chunks. Context that does not answer → fallback, sent by the LLM under rule 3 (ADR-019: no similarity threshold separates).
2. **Metadata pre-filter beats post-filter**: use `WHERE collection = ...` before ORDER BY, not after LIMIT.
3. **One ranked list until a second one can be weighted**: RRF's equal ballot sank two sparse repairs (ADR-015, ADR-017), so retrieval is dense-only (ADR-018). A second list returns only with a weight RAGAS can tune.
4. **No reranker until one is measured to help**: ADR-005 measured two local cross-encoders over the top 20 on 2026-09-21. Both dropped a protected golden-set path from the top 3, so neither ships. `settings.reranker_model` keeps a re-measurement one setting away.
5. **Chunk-source metadata is a citation, not decoration**: every answer names its sources.

## Anti-patterns

- Hallucinated citations (LLM invents a chunk that doesn't exist)
- Silent score normalization (invalidates fusion math)
- Chunk deduplication at retrieval time (should happen at index time)
- LLM temperature > 0.3 in production (accuracy over creativity for grounded QA)

## References

- Cormack et al. (2009) — Reciprocal Rank Fusion
- BGE embedding model card — https://huggingface.co/BAAI/bge-small-en-v1.5
- RAGAS docs — https://docs.ragas.io/
