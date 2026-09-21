-- Health checks and query plan baselines
-- Run after `make index-corpus` to verify index usage.

-- 1. Extension versions
SELECT extname, extversion FROM pg_extension
WHERE extname IN ('vector', 'pg_trgm', 'btree_gin');

-- 2. Chunk counts per collection (sanity check)
SELECT collection, source_project, COUNT(*) AS chunk_count
FROM chunks
GROUP BY collection, source_project
ORDER BY collection, source_project;

-- 3. HNSW index size (should be a few MB for <500 chunks)
SELECT
    schemaname,
    tablename,
    indexname,
    pg_size_pretty(pg_relation_size(indexname::regclass)) AS index_size
FROM pg_indexes
WHERE tablename IN ('chunks', 'query_log')
ORDER BY tablename, indexname;

-- 4. Query plan baseline — dense-only retrieval
-- NOTE: at corpus scale (304 rows) the planner legitimately prefers a Seq Scan;
-- the table fits in a handful of pages and HNSW has no work to save. That is not
-- a fault. Section 6 proves the index is usable by forcing it. Capture these
-- plans as the regression baseline and compare shape, not index choice.
--
-- The probe vector is taken by `ORDER BY id LIMIT 1`, not `WHERE id = 1`: id is
-- BIGSERIAL and replace-by-scope deletes and reinserts, so the sequence never
-- revisits 1 and the old form silently returned NULL after the first reindex.
-- BEGIN/COMMIT is required: a bare SET LOCAL outside a transaction block is a
-- no-op that only warns, so this baseline was never actually measured at
-- ef_search = 40.
BEGIN;
SET LOCAL hnsw.ef_search = 40;
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT id, source_project, adr_id, content
FROM chunks
WHERE collection = 'decisions'
ORDER BY embedding <=> (SELECT embedding FROM chunks ORDER BY id LIMIT 1)
LIMIT 5;
COMMIT;

-- 5. Query plan baseline — the fused query retrieval actually runs
-- Mirrors HYBRID_QUERY in data_platform_rag/retrieval/hybrid_search.py with the
-- parameters inlined: q002's question, top_k = 20, rrf_k = 60, and the first
-- chunk's embedding standing in for a query vector. If that constant changes,
-- this section changes with it.
--
-- It uses neither index, and that is expected, not a fault. At 304 rows the dense
-- side is a Seq Scan (see section 4), and the sparse side has no `@@` predicate
-- for the GIN index to serve: ts_rank_cd is computed for every candidate before
-- either list is limited (known gap, recorded in ADR-015 Consequences).
--
-- What to check: the plan shape, not the row count. For this question the sparse
-- side reports rows=0 with `Rows Removed by Filter: 304`, because plain
-- plainto_tsquery ANDs every term. That is the known defect recorded in ADR-003
-- Amendment 1 §B, left open after ADR-015 was rejected -- an observation, not
-- the desired state.
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
WITH q AS (
  SELECT (SELECT embedding FROM chunks ORDER BY id LIMIT 1) AS v,
         plainto_tsquery('english',
           'Why does the Databricks project use one unified Lakeflow pipeline '
           'instead of many parametrized notebooks?') AS t
),
candidates AS (
  SELECT c.id, c.embedding <=> q.v AS dense_dist, ts_rank_cd(c.content_tsv, q.t) AS sparse_score
  FROM chunks c, q
  WHERE c.collection = ANY('{decisions,architecture}'::text[])
),
dense_ranked AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY dense_dist ASC, id ASC) AS dense_rank
  FROM candidates ORDER BY dense_dist ASC, id ASC LIMIT 20
),
sparse_ranked AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY sparse_score DESC, id ASC) AS sparse_rank
  FROM candidates WHERE sparse_score > 0 ORDER BY sparse_score DESC, id ASC LIMIT 20
)
SELECT c.id,
  COALESCE(1.0 / (60 + d.dense_rank), 0) + COALESCE(1.0 / (60 + s.sparse_rank), 0) AS rrf_score
FROM candidates c
LEFT JOIN dense_ranked  d USING (id)
LEFT JOIN sparse_ranked s USING (id)
WHERE d.dense_rank IS NOT NULL OR s.sparse_rank IS NOT NULL
ORDER BY rrf_score DESC, c.id ASC
LIMIT 20;

-- 6. Proof that the HNSW index is usable, independent of what the planner picks
-- Must report "Index Scan using idx_chunks_embedding_hnsw", and must return the
-- same ids as section 4. SET LOCAL needs a transaction block to have any effect.
BEGIN;
SET LOCAL hnsw.ef_search = 40;
SET LOCAL enable_seqscan = off;
EXPLAIN (ANALYZE, COSTS OFF)
SELECT id FROM chunks
ORDER BY embedding <=> (SELECT embedding FROM chunks ORDER BY id LIMIT 1)
LIMIT 5;
COMMIT;

-- 7. Provenance — indexed corpus == verified corpus (ADR-013)
-- Compare against MANIFEST.json; `make index-corpus-verify` does this in Python.
SELECT source_project, commit_sha, chunk_count, embedding_model, indexed_at
FROM corpus_snapshot
ORDER BY source_project;
