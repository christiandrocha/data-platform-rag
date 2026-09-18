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

-- 5. Query plan baseline — hybrid (dense + sparse)
-- Should use idx_chunks_content_tsv_gin AND idx_chunks_embedding_hnsw.
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
WITH dense AS (
    SELECT id, embedding <=> (SELECT embedding FROM chunks ORDER BY id LIMIT 1) AS dense_dist
    FROM chunks
    WHERE collection = 'decisions'
    ORDER BY dense_dist LIMIT 20
),
sparse AS (
    SELECT id, ts_rank_cd(content_tsv, plainto_tsquery('english', 'debezium cdc snowflake')) AS sparse_score
    FROM chunks
    WHERE collection = 'decisions' AND content_tsv @@ plainto_tsquery('english', 'debezium cdc snowflake')
    ORDER BY sparse_score DESC LIMIT 20
)
SELECT COALESCE(d.id, s.id) AS id, d.dense_dist, s.sparse_score
FROM dense d FULL OUTER JOIN sparse s USING (id)
LIMIT 10;

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
