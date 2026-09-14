-- Extensions required for data-platform-rag
-- Run once per database.

CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector for dense embeddings
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- trigram similarity for fuzzy matching (backup to tsvector)
CREATE EXTENSION IF NOT EXISTS btree_gin;   -- allow GIN on scalar columns (for metadata filters)

-- Verify installation
SELECT extname, extversion FROM pg_extension
WHERE extname IN ('vector', 'pg_trgm', 'btree_gin')
ORDER BY extname;
