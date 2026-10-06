-- query_log.origin: who asked. Implements ADR-008 (DESIGN, "Data contracts").
--
-- `make eval` stage 1 asks every golden-set question through the product path,
-- `answer()`, so each eval question writes a real `query_log` row and a real
-- trace, which its RAGAS scores attach to. Without a mark, those rows would be
-- counted as visitors. This column is the mark: 'visitor' (the page) or 'eval'.
--
-- Rows written before this file existed get 'visitor', which is what they are.
-- No CHECK constraint: ADD CONSTRAINT has no IF NOT EXISTS in Postgres 16, and the
-- value comes from a Literal in `contracts.Origin`.
--
-- Run after 04_query_log_product.sql. Create-only and idempotent, like the rest
-- of the 00-05 sequence: a second run against a populated database is a no-op.

ALTER TABLE query_log
    ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'visitor';

COMMENT ON COLUMN query_log.origin IS
    'visitor (the page) or eval (make eval stage 1). ADR-008';
