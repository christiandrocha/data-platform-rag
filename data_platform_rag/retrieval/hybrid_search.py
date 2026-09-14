"""Hybrid search — dense (pgvector) + sparse (tsvector) via RRF.

The one-query SQL implementation lives in .claude/kb/rag/hybrid-retrieval.md
and is materialized here as HYBRID_QUERY. Parameters:
    $1 : query embedding (vector(384))
    $2 : query text for tsquery
    $3 : collection array (text[])
"""

from __future__ import annotations

HYBRID_QUERY = """
WITH candidates AS (
  SELECT
    id, content, source_project, adr_id, source_path,
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
  FROM candidates
  WHERE sparse_score > 0
  ORDER BY sparse_score DESC LIMIT 20
)
SELECT
  c.id, c.content, c.source_project, c.adr_id, c.source_path,
  c.dense_dist, c.sparse_score,
  (1.0 / (60 + COALESCE(d.dense_rank, 999))) +
  (1.0 / (60 + COALESCE(s.sparse_rank, 999))) AS rrf_score
FROM candidates c
LEFT JOIN dense_ranked  d USING (id)
LEFT JOIN sparse_ranked s USING (id)
WHERE d.dense_rank IS NOT NULL OR s.sparse_rank IS NOT NULL
ORDER BY rrf_score DESC
LIMIT 20;
"""


def build_hybrid_query(collections: list[str]) -> str:
    """Return the parameterized hybrid query."""
    if not collections:
        raise ValueError("At least one collection must be specified")
    return HYBRID_QUERY
