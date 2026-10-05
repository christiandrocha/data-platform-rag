-- query_log for the product query path. Implements ADR-021.
--
-- `query_log` was written for the pipeline before ADR-018 and ADR-019: it has
-- columns for an intent classifier and a reranker that do not run, and none for
-- what a query now produces. This file adds the missing columns. It removes
-- nothing: the bootstrap path never drops (ADR-013), and old rows keep NULLs in
-- the new columns, because those values did not exist when they were written.
--
-- Run after 03_corpus_snapshot.sql. Create-only and idempotent, like the rest of
-- the 00-04 sequence: a second run against a populated database is a no-op.

ALTER TABLE query_log
    ADD COLUMN IF NOT EXISTS output_class TEXT
        CHECK (output_class IN ('fallback', 'non_compliant_refusal', 'empty', 'answer')),
    ADD COLUMN IF NOT EXISTS failed BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS error TEXT,
    ADD COLUMN IF NOT EXISTS model TEXT,
    ADD COLUMN IF NOT EXISTS system_prompt_version TEXT,
    ADD COLUMN IF NOT EXISTS context_format_version TEXT,
    ADD COLUMN IF NOT EXISTS input_tokens INT,
    ADD COLUMN IF NOT EXISTS output_tokens INT,
    ADD COLUMN IF NOT EXISTS stop_reason TEXT,
    ADD COLUMN IF NOT EXISTS corpus_commits TEXT[],
    ADD COLUMN IF NOT EXISTS embedding_model TEXT,
    ADD COLUMN IF NOT EXISTS trace_id TEXT;

COMMENT ON TABLE query_log IS
    'One row per product query (ADR-021), failed ones included. Source of truth for analytics; Langfuse holds the trace.';

-- Columns the current pipeline leaves NULL, kept because the bootstrap path never drops
COMMENT ON COLUMN query_log.intent IS
    'Always NULL since ADR-018: no intent classifier runs. Kept, not dropped (ADR-013, ADR-021).';
COMMENT ON COLUMN query_log.reranker_top_score IS
    'Always NULL: ADR-005 rejected the reranker. Kept, not dropped (ADR-013, ADR-021).';

-- Existing columns whose meaning ADR-018 to ADR-021 fixed
COMMENT ON COLUMN query_log.retrieved_scores IS
    'Cosine distances of retrieved_ids, parallel to it. Lower is closer (ADR-018).';
COMMENT ON COLUMN query_log.fallback_fired IS
    'True when the visitor got no answer: output_class fallback, non_compliant_refusal or empty (ADR-020 B2 grouping).';
COMMENT ON COLUMN query_log.answer_length IS
    'Characters shown to the visitor. 0 unless output_class is answer.';

-- New columns
COMMENT ON COLUMN query_log.output_class IS
    'ADR-020 class of the LLM output, by exact match. NULL only when failed.';
COMMENT ON COLUMN query_log.failed IS
    'Retrieval or the Anthropic call raised. The visitor saw the could-not-answer message, never the fallback.';
COMMENT ON COLUMN query_log.error IS
    'Exception class and message of a failed query, at most 500 characters.';
COMMENT ON COLUMN query_log.model IS
    'Model id as the API reported it, not as requested.';
COMMENT ON COLUMN query_log.corpus_commits IS
    'project@sha of the retrieved chunks, taken in the insert. Survives a reindex, unlike a snapshot id (ADR-021).';
COMMENT ON COLUMN query_log.embedding_model IS
    'Embedding model of the retrieved chunks'' snapshot.';
COMMENT ON COLUMN query_log.trace_id IS
    'Langfuse trace of this query. NULL when Langfuse is disabled.';
