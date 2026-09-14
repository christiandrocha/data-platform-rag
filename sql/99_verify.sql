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
-- If HNSW index is not used, something is wrong. Look for "Index Scan using idx_chunks_embedding_hnsw".
SET LOCAL hnsw.ef_search = 40;
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT id, source_project, adr_id, content
FROM chunks
WHERE collection = 'decisions'
ORDER BY embedding <=> (SELECT embedding FROM chunks WHERE id = 1)
LIMIT 5;

-- 5. Query plan baseline — hybrid (dense + sparse)
-- Should use idx_chunks_content_tsv_gin AND idx_chunks_embedding_hnsw.
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
WITH dense AS (
    SELECT id, embedding <=> (SELECT embedding FROM chunks WHERE id = 1) AS dense_dist
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
