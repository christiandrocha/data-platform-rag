-- Destructive reset for data-platform-rag.
--
-- These statements used to live at the top of sql/01_schema.sql, which
-- `make bootstrap` runs. That made the documented ordinary way to start the
-- database silently discard a populated index (ADR-013 section 5). They are
-- evicted here, into a file that bootstrap does not run.
--
-- The only path to this file is `make reset-db`. Nothing else should call it.
--
-- Order matters: chunks holds a foreign key into corpus_snapshot, so the
-- CASCADE on corpus_snapshot would take chunks with it anyway. Both are named
-- explicitly so that reading this file tells you everything it destroys.

DROP TABLE IF EXISTS chunks CASCADE;
DROP TABLE IF EXISTS corpus_snapshot CASCADE;
DROP TABLE IF EXISTS query_log CASCADE;

SELECT 'reset complete — run make bootstrap to recreate' AS status;
