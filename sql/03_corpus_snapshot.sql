-- Corpus provenance. Implements ADR-013.
--
-- ADR-012 made the on-disk snapshot provenance-bearing: MANIFEST.json records,
-- per project, the repo URL, the 40-character commit SHA, and a sha256 per
-- extracted file. That chain broke here — `chunks` had no column that could hold
-- a commit SHA, so the assertion ADR-012 exists to enable (indexed corpus ==
-- verified corpus) could not be written as a query.
--
-- Run after 01_schema.sql: this file alters `chunks`.
-- Create-only and idempotent, like the rest of the 00-03 sequence.

-- ============================================================================
-- corpus_snapshot — one row per (fetch, project)
-- ============================================================================
-- The grain is deliberate (ADR-013 section 1): it is the grain at which indexing
-- replaces, and the grain at which a commit SHA is meaningful. A snapshot
-- covering two projects produces two rows, which repeats manifest_created_at
-- across them. That denormalisation is preferred to a third table whose only
-- purpose would be to hold one timestamp.

CREATE TABLE IF NOT EXISTS corpus_snapshot (
    id                      BIGSERIAL PRIMARY KEY,

    -- Provenance, copied from MANIFEST.json
    source_project          TEXT NOT NULL
                            CHECK (source_project IN ('sdd-kafka-snowflake-2', 'sdd-kafka-databricks')),
    repo_url                TEXT NOT NULL,
    commit_sha              CHAR(40) NOT NULL CHECK (commit_sha ~ '^[0-9a-f]{40}$'),
    file_count              INT NOT NULL CHECK (file_count > 0),
    manifest_created_at     TIMESTAMPTZ NOT NULL,
    manifest_schema_version INT NOT NULL CHECK (manifest_schema_version >= 1),

    -- Which embedding space these vectors live in. VECTOR(384) accepts vectors
    -- from ANY 384-dimensional model, so without this column an index built from
    -- two different models is indistinguishable from a healthy one.
    embedding_model         TEXT NOT NULL,
    embedding_dim           INT NOT NULL CHECK (embedding_dim = 384),

    chunk_count             INT NOT NULL CHECK (chunk_count >= 0),
    indexed_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One live snapshot per project. This is what makes a mixed-commit index
    -- unrepresentable rather than merely unlikely: replace-by-scope deletes this
    -- row before inserting the new one, and the cascade below takes the old
    -- project's chunks with it.
    CONSTRAINT uq_corpus_snapshot_project UNIQUE (source_project),

    -- Exists solely as the target of the composite foreign key on chunks.
    CONSTRAINT uq_corpus_snapshot_id_project UNIQUE (id, source_project)
);

COMMENT ON TABLE corpus_snapshot IS
    'Corpus provenance: which commit and which embedding model produced the rows in chunks. See ADR-013.';
COMMENT ON COLUMN corpus_snapshot.embedding_model IS
    'The model that produced these vectors. Part of the re-index short-circuit key: changing the model forces a re-embed rather than silently mixing two embedding spaces.';
COMMENT ON CONSTRAINT uq_corpus_snapshot_project ON corpus_snapshot IS
    'One live snapshot per project. Replace-by-scope depends on this.';

-- ============================================================================
-- chunks.snapshot_id — every chunk names the fetch it descends from
-- ============================================================================

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS snapshot_id BIGINT NOT NULL;

-- Composite on purpose (ADR-013 section 2). A plain snapshot_id would let a
-- chunk claim a source_project different from its snapshot's -- exactly the
-- corruption replace-by-scope is designed to make impossible. Referencing
-- (id, source_project) makes the database reject it, rather than leaving it to
-- the writer to remember.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_chunks_snapshot'
    ) THEN
        ALTER TABLE chunks
            ADD CONSTRAINT fk_chunks_snapshot
            FOREIGN KEY (snapshot_id, source_project)
            REFERENCES corpus_snapshot (id, source_project)
            ON DELETE CASCADE;
    END IF;
END
$$;

-- Supports the cascade and the per-project scope queries. Postgres does not
-- index foreign keys automatically, and every delete in this design is a
-- delete of a parent row.
CREATE INDEX IF NOT EXISTS idx_chunks_snapshot ON chunks (snapshot_id);

COMMENT ON COLUMN chunks.snapshot_id IS
    'The corpus_snapshot row this chunk descends from. ON DELETE CASCADE: deleting a project''s snapshot row is how replace-by-scope clears its chunks.';
