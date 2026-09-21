# SHIPPED: Embedding and the pgvector writer

## Metadata

| Field | Value |
|-------|-------|
| Feature | corpus-indexing-writer (slice 2 of 2) |
| Shipped date | 2026-09-18 |
| PR | [#1](https://github.com/christiandrocha/data-platform-rag/pull/1), merged by rebase |
| Deploy | **none exists.** `ui/app.py` is a TODO stub and no Streamlit Cloud URL has ever been published |
| ADR | [ADR-013](../../../../docs/adr/ADR-013-corpus-provenance-in-postgres.md) |

> Written retroactively on 2026-09-21.

## What users see

**Nothing yet** — but this is the slice after which there is something to
retrieve. 304 rows live in Postgres with 384-dimensional embeddings, each
carrying a `snapshot_id` into `corpus_snapshot`, which records the commit SHA and
the embedding model that produced it.

The observable consequence is an assertion that could not previously be written
as a query: `make index-corpus-verify` compares what is indexed against what the
manifest says and reports *indexed corpus == verified corpus*. A score can now
name the commit it was measured against.

## What we learned

**Replace-by-scope, not upsert.** `ON CONFLICT DO UPDATE` leaves orphan rows when
a later commit produces fewer chunks, and an orphan is retrievable text that is
no longer in the corpus. One transaction per project scope makes that state
unrepresentable. This became an AGENTS.md boundary rather than a note in the ADR.

**`DROP` does not belong in the bootstrap path.** `sql/01` and `02` opened with
drops, so `make bootstrap` against a populated database was destructive by
accident. Every destructive statement moved to `sql/90_reset.sql`, reached only
by `make reset-db`.

**Two pre-existing defects in `sql/99_verify.sql` were found by running it** —
it probed a row that cannot exist and never set `ef_search`. A verification
script that has never been executed verifies nothing.

## Retrospective for the log

- **Unexecuted code is not working code, and this project keeps proving it.**
  `99_verify.sql` here; `HYBRID_QUERY` in the next feature, which had never run at
  all; `ragas.yml` on 2026-09-21, which had never got past its first step.
- **The dimension guard belongs before the transaction opens**, not inside it.
- **A test database built from the same `sql/` files as production** is the only
  way the schema under test is the schema that ships.
