# HNSW parameter tuning for data-platform-rag

## Parameters

| Parameter | Default | Meaning | When to change |
|-----------|---------|---------|---------------|
| `m` | 16 | Connections per node | Increase if recall < target after ef_search tuning |
| `ef_construction` | 64 | Build-time candidate list size | Increase for better graph, slower build |
| `ef_search` | 40 (session) | Query-time candidate list | Increase for accuracy, decrease for latency |

## Tuning procedure

1. Baseline: build with defaults, run golden set, record RAGAS Context Recall
2. Grid search `ef_search` in {20, 40, 80, 160} at query time
3. If Context Recall ceiling < 0.9, increase `m` to 24 or 32 and rebuild
4. If build time > 60s becomes a problem, cap `m` and raise `ef_search` instead

## Session parameter setting

```python
async def hybrid_search(pool, query, ...):
    async with pool.acquire() as conn:
        await conn.execute("SET LOCAL hnsw.ef_search = 40")
        rows = await conn.fetch(HYBRID_QUERY, ...)
```

Never set `hnsw.ef_search` globally — it's a per-query trade-off.

## References

- pgvector README — https://github.com/pgvector/pgvector
- Malkov & Yashunin (2016) — original HNSW paper
