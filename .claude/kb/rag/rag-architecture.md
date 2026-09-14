# RAG architecture reference — data-platform-rag

## Pipeline stages

```
Query → Intent classifier → Hybrid retrieval → Reranking → Threshold check → LLM or Fallback
```

## Design principles

1. **Grounded or silent**: never generate answers without cited chunks. Below-threshold → fallback.
2. **Metadata pre-filter beats post-filter**: use `WHERE collection = ...` before ORDER BY, not after LIMIT.
3. **Reciprocal Rank Fusion for hybrid**: no score normalization needed, robust to score-scale mismatch.
4. **Cross-encoder rerank on top-20 candidates**: keeps latency bounded, meaningful RAGAS lift.
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
