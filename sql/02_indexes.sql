-- Index strategy for data-platform-rag
-- Every index here has an ADR justifying its parameters. Do not add indexes ad-hoc.

-- ============================================================================
-- HNSW index on embedding column
-- ============================================================================
-- Parameters (ADR-004-hnsw-parameter-tuning.md justifies these):
--   m = 16                  → default, adequate for <10k chunks
--   ef_construction = 64    → default, build-time quality
--   Cosine distance         → matches bge-small-en-v1.5 training objective
--
-- ef_search is a runtime parameter, set per-session in retrieval code:
--   SET LOCAL hnsw.ef_search = 40;   (default 40, higher = more accurate, slower)
--
-- HNSW over IVFFlat because: (a) no training step required (b) better recall at
-- our small scale (c) supports incremental inserts without reclustering.

CREATE INDEX idx_chunks_embedding_hnsw
    ON chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

COMMENT ON INDEX idx_chunks_embedding_hnsw IS
    'HNSW cosine similarity. Parameters justified in ADR-004. ef_search set per-session in retrieval code.';

-- ============================================================================
-- GIN index on tsvector — sparse retrieval (BM25-like ranking via ts_rank_cd)
-- ============================================================================
-- GIN is optimal for tsvector queries. Trigger-based updates would let us drop
-- the generated column, but generated STORED is cleaner and PG 12+ handles it well.

CREATE INDEX idx_chunks_content_tsv_gin
    ON chunks
    USING gin (content_tsv);

COMMENT ON INDEX idx_chunks_content_tsv_gin IS
    'Sparse retrieval for hybrid search. Fused with dense scores via reciprocal rank fusion.';

-- ============================================================================
-- Metadata filter indexes
-- ============================================================================
-- These support pre-filtering before vector similarity — a common speedup pattern.
-- Composite index for the most common filter combination: collection + source_project.

CREATE INDEX idx_chunks_collection_project
    ON chunks (collection, source_project);

CREATE INDEX idx_chunks_topic ON chunks (topic) WHERE topic IS NOT NULL;
CREATE INDEX idx_chunks_adr_id ON chunks (adr_id) WHERE adr_id IS NOT NULL;

-- GIN on the keywords array, supporting the overlap operator (&&). Partial,
-- matching the two indexes above: NULL means extraction did not run, and those
-- rows can never satisfy an overlap predicate.
-- Reserved for a future pre-filter; no v1 query uses it yet. It is created now
-- so that enabling the pre-filter is a retrieval-code change only, with no
-- migration and no reindex.
CREATE INDEX idx_chunks_keywords_gin
    ON chunks
    USING gin (keywords)
    WHERE keywords IS NOT NULL;

COMMENT ON INDEX idx_chunks_keywords_gin IS
    'Array overlap (&&) pre-filter on extracted noun phrases. Unused in v1 retrieval; see ADR-002 and contracts.py::ChunkMetadata.';

-- ============================================================================
-- Query log indexes (analytics + fallback ratio computation)
-- ============================================================================

CREATE INDEX idx_query_log_ts ON query_log (ts DESC);
CREATE INDEX idx_query_log_fallback ON query_log (fallback_fired, ts DESC) WHERE fallback_fired = TRUE;
