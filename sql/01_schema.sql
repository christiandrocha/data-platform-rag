-- Schema for data-platform-rag
-- Two logical collections, one physical table with `collection` column for scan efficiency.
-- Rationale: 150-500 chunks is too small to justify partitioning. Single table + collection column
-- keeps queries simple and lets PostgreSQL query planner optimize with a single index strategy.

-- Drop for clean rebuilds during development
-- Comment out in production migrations
DROP TABLE IF EXISTS chunks CASCADE;
DROP TABLE IF EXISTS query_log CASCADE;

-- Chunks — the indexed knowledge base
CREATE TABLE chunks (
    id              BIGSERIAL PRIMARY KEY,
    collection      TEXT NOT NULL CHECK (collection IN ('decisions', 'architecture')),

    -- Content
    content         TEXT NOT NULL,
    content_tsv     TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,

    -- Embedding (bge-small-en-v1.5 → 384 dims)
    embedding       VECTOR(384) NOT NULL,

    -- Provenance metadata (used for filtering AND citation in the UI)
    source_project  TEXT NOT NULL,                    -- sdd-kafka-snowflake-2 | sdd-kafka-databricks (this repo is NOT a corpus source)
    source_type     TEXT NOT NULL,                    -- adr | readme | contract | macro | schema
    source_path     TEXT NOT NULL,                    -- e.g. docs/adr/ADR-0019.md
    source_anchor   TEXT,                             -- e.g. section heading within the file

    -- Domain metadata (used for retrieval-time filtering)
    adr_id          TEXT,                             -- e.g. ADR-0019 (nullable — only ADR chunks)
    topic           TEXT,                             -- e.g. ingestion, cost-governance, cdc-strategy
    status          TEXT,                             -- accepted | superseded | resolved (ADRs only)

    -- Noun phrases extracted at index time. Nullable ON PURPOSE, no DEFAULT:
    -- NULL means "extraction did not run for this chunk", '{}' means "ran, found
    -- nothing". The distinction matters because `keywords && ARRAY[...]` yields
    -- NULL for the first and FALSE for the second. See contracts.py::ChunkMetadata.
    keywords        TEXT[],

    -- Bookkeeping
    chunk_index     INT NOT NULL DEFAULT 0,           -- position within source document
    token_count     INT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Deduplication key: same source_path + chunk_index means "same chunk"
    UNIQUE (source_path, chunk_index)
);

COMMENT ON TABLE chunks IS 'Vector store for data-platform-rag. Two collections (decisions/architecture) sharing one physical table. See ADR-002.';
COMMENT ON COLUMN chunks.embedding IS 'bge-small-en-v1.5 dense embedding, 384 dims. HNSW-indexed.';
COMMENT ON COLUMN chunks.content_tsv IS 'Generated tsvector for sparse (BM25-like) hybrid retrieval.';
COMMENT ON COLUMN chunks.keywords IS
    'Noun phrases extracted at index time (regex + stop-word filter, no NER). Unused by v1 retrieval; reserved for a future keywords && ARRAY[...] pre-filter. NULL = not extracted, {} = extracted and empty.';

-- ----------------------------------------------------------------------------
-- On pg_trgm (enabled in sql/00_extensions.sql)
-- ----------------------------------------------------------------------------
-- pg_trgm is NOT the sparse retrieval mechanism. Primary sparse retrieval is
-- to_tsvector + ts_rank_cd over chunks.content_tsv, fused with dense pgvector
-- results via reciprocal rank fusion, per ADR-003. pg_trgm is enabled only as a
-- backup for fuzzy matching (typo-tolerant lookups on identifiers such as
-- 'ADR-0019' or table names), and nothing in the v1 retrieval path calls it.
-- Reaching for pg_trgm as the sparse half of hybrid retrieval would silently
-- replace a ranked, language-aware scorer with trigram overlap. Do not.


-- Query log — every retrieval attempt, for RAGAS regression + fallback analysis
CREATE TABLE query_log (
    id                  BIGSERIAL PRIMARY KEY,
    ts                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    query_text          TEXT NOT NULL,
    intent              TEXT,                          -- decision | architecture | comparison | hybrid
    retrieved_ids       BIGINT[],                      -- chunks.id values, in rank order
    retrieved_scores    REAL[],                        -- parallel to retrieved_ids
    reranker_top_score  REAL,                          -- top-1 score after reranking
    fallback_fired      BOOLEAN NOT NULL DEFAULT FALSE,
    answer_length       INT,                           -- chars of generated answer (0 if fallback)
    latency_ms          INT
);

COMMENT ON TABLE query_log IS 'Every retrieval attempt. Feeds fallback analytics and RAGAS baseline.';
