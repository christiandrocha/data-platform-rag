# Hybrid retrieval — dense + sparse + RRF

## The one-query implementation

Source of truth: `HYBRID_QUERY` in `data_platform_rag/retrieval/hybrid_search.py`.
This is a copy for reading; if the two differ, the code wins and this page is the
defect. Placeholders are psycopg (`%(name)s`), bound by `search()`.

```sql
WITH candidates AS (
  SELECT
    id, content, collection,
    source_project, source_type, source_path, source_anchor,
    adr_id, topic, status, keywords, chunk_index, token_count,
    embedding <=> %(query_vector)s::vector AS dense_dist,
    ts_rank_cd(content_tsv, plainto_tsquery('english', %(query_text)s)) AS sparse_score
  FROM chunks
  WHERE collection = ANY(%(collections)s::text[])
),
dense_ranked AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY dense_dist ASC, id ASC) AS dense_rank
  FROM candidates ORDER BY dense_dist ASC, id ASC LIMIT %(top_k)s
),
sparse_ranked AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY sparse_score DESC, id ASC) AS sparse_rank
  FROM candidates WHERE sparse_score > 0
  ORDER BY sparse_score DESC, id ASC LIMIT %(top_k)s
)
SELECT
  c.*,  -- every ChunkMetadata column, plus dense_dist and sparse_score
  d.dense_rank, s.sparse_rank,
  COALESCE(1.0 / (%(rrf_k)s + d.dense_rank), 0)
  + COALESCE(1.0 / (%(rrf_k)s + s.sparse_rank), 0) AS rrf_score
FROM candidates c
LEFT JOIN dense_ranked  d USING (id)
LEFT JOIN sparse_ranked s USING (id)
WHERE d.dense_rank IS NOT NULL OR s.sparse_rank IS NOT NULL
ORDER BY rrf_score DESC, c.id ASC
LIMIT %(top_k)s;
```

Three details worth knowing before changing it:

- **A missing side contributes 0**, not `1/(60+999)` (ADR-003 Amendment 1).
- **The sparse side is plain `plainto_tsquery` and is empty for most
  questions** (ADR-003 §B). It ANDs every term, and a question-shaped query
  matched 0 of 304 chunks for four of five golden questions. OR-joining was tried
  and rejected (ADR-015): recall did not move, q001 lost rank 1 to a tie.
- **Both `ROW_NUMBER()` windows break ties by `id`.** Without the tiebreak a
  tied rank follows heap order and can change after a reindex. Found under
  ADR-015's OR query, where ties on `sparse_score` were common; kept after it.

## Parameters and rationale

| Parameter | Value | Justification |
|-----------|-------|--------------|
| dense limit | `settings.hybrid_top_k` (currently 20) | Cover-and-rerank pattern |
| sparse limit | `settings.hybrid_top_k` | Same parameter; one `top_k` bounds both sides and the output |
| RRF k | `RRF_K` = 60, module constant | Cormack et al.; a constant, not a setting, by ADR-003 |
| sparse weight | none | RRF sums both sides unweighted; no weight until RAGAS can tune one (ADR-003) |
| final limit | `settings.hybrid_top_k` | Feed to reranker, keep `settings.rerank_top_k` (currently 3) |

## When hybrid loses to dense-only

- Purely paraphrastic queries with no domain vocabulary overlap → sparse contributes noise
- Very short queries (<3 tokens) → sparse ranking is noisy
- **If the sparse side is ever populated for questions, out-of-scope questions
  look more confident, not less.** Under ADR-015's OR, q005's top score rose
  0.01639 → 0.02964: generic lexemes still match, so a second contribution
  arrives. Any fallback threshold on `rrf_score` must be set knowing this
  (ADR-005, ADR-006).

Golden set should include both cases to keep the fusion honest.
