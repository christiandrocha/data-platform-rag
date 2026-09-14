# Hybrid retrieval — dense + sparse + RRF

## The one-query implementation

```sql
WITH candidates AS (
  SELECT
    id, content, source_project, adr_id,
    embedding <=> $1::vector AS dense_dist,
    ts_rank_cd(content_tsv, plainto_tsquery('english', $2)) AS sparse_score
  FROM chunks
  WHERE collection = ANY($3::text[])
),
dense_ranked AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY dense_dist ASC) AS dense_rank
  FROM candidates ORDER BY dense_dist ASC LIMIT 20
),
sparse_ranked AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY sparse_score DESC) AS sparse_rank
  FROM candidates WHERE sparse_score > 0 ORDER BY sparse_score DESC LIMIT 20
)
SELECT
  c.id, c.content, c.source_project, c.adr_id,
  (1.0 / (60 + COALESCE(d.dense_rank, 999))) +
  (1.0 / (60 + COALESCE(s.sparse_rank, 999))) AS rrf_score
FROM candidates c
LEFT JOIN dense_ranked  d USING (id)
LEFT JOIN sparse_ranked s USING (id)
WHERE d.dense_rank IS NOT NULL OR s.sparse_rank IS NOT NULL
ORDER BY rrf_score DESC
LIMIT 20;
```

## Parameters and rationale

| Parameter | Value | Justification |
|-----------|-------|--------------|
| dense limit | 20 | Cover-and-rerank pattern, top-3 after rerank |
| sparse limit | 20 | Same |
| RRF k | 60 | Cormack et al. canonical value |
| final limit | 20 | Feed 20 to reranker, keep `settings.rerank_top_k` (currently 3) |

## When hybrid loses to dense-only

- Purely paraphrastic queries with no domain vocabulary overlap → sparse contributes noise
- Very short queries (<3 tokens) → sparse ranking is noisy

Golden set should include both cases to keep the fusion honest.
