# DEFINE: Embedding and the pgvector writer

> Slice 2 of `corpus-indexing`: take the 304 chunks slice 1 measured but never
> stored, embed them, and write them into `chunks` with provenance strong enough
> that a score can name the corpus commit it was measured against.

## Metadata

| Field | Value |
|-------|-------|
| Feature | corpus-indexing-writer (slice 2 of 2) |
| Predecessor | [corpus-indexing slice 1](../corpus-indexing/BUILD_REPORT.md) — merged at `06778d8` |
| Date | 2026-09-18 |
| Author | christiandrocha |
| Status | Ready for Design |
| Clarity Score | 13/15 |

## Problem statement

Slice 1 ended with a corpus that is acquired, hashed, chunked and measured — and
a database that has never held a row. `make index-corpus` prints a message
saying embedding is not built and exits 1. `indexer/embedder.py` is three
functions that raise `NotImplementedError`. There is no `writer.py`. The 304
chunks exist only as objects inside a dry run that discards them.

Everything downstream is blocked on that gap, and blocked in a way that is easy
to under-read: retrieval, reranking, generation, the ADR-004 embedding
benchmark, and every RAGAS number the README reserves a badge for. None of them
are hard problems waiting on a hard decision. They are waiting on rows.

Three further holes are specific to this slice, all found by reading the DDL and
the Makefile against what slice 1 built:

**The provenance chain breaks at the database boundary.** ADR-012's purpose is
that a score can name the corpus commit it was measured against. The manifest
records that commit; `chunks` has no column that can hold it. `contracts.py`
already carries `schema_version: int = 1` on `CorpusManifest` specifically
because "slice 2 must store these SHAs beside the indexed rows" — the contract
anticipated a schema this slice has to supply. Until it does, the *indexed
corpus == verified corpus* assertion is unmakeable and the gate at ADR-011
Layer 1 verifies a snapshot that nothing proves the index came from.

**`make reindex` can empty the index and leave it empty.** It runs
`TRUNCATE chunks;` as one `psql -c`, then calls `make index-corpus` as a
separate process. The truncate commits on its own. Any failure after it — a
model that will not load, a network fetch for the vocabulary, one oversize
chunk, Ctrl-C — leaves zero rows and a system that answers nothing, with no step
that put it there still running. `make reindex` is named in AGENTS.md as
"(destructive)", which describes the intent and not this failure mode.

**`make bootstrap` is destructive of an index nobody said goodbye to.**
`sql/01_schema.sql` opens with `DROP TABLE IF EXISTS chunks CASCADE`. The
comment above it says "Comment out in production migrations", so the hazard was
seen; the target that runs it is the one documented as the ordinary way to start
the database. Today that is harmless because the table is always empty. The
moment this slice lands, `make bootstrap` silently discards a populated index.

## Users

| User | Role | Pain point |
|------|------|-----------|
| Christian (operator) | Runs `make index-corpus`, then the eval | Has 304 measured chunks and no way to store them. Cannot run a single retrieval against the corpus this whole project is about |
| Christian (curator) | Writes the remaining 45 golden-set questions | Writes expected answers blind. Cannot check whether a question he just wrote actually retrieves the ADR he anchored it to — the cheapest possible feedback loop, and it does not exist |
| ADR-004 (embedding benchmark) | Needs a populated index to benchmark against | Named as a consumer in slice 1's DEFINE and still blocked. It cannot compare two models without a writer that can load each of them |
| The eval gate (`ragas.yml`) | Asserts indexed == verified | Has a manifest on disk and no counterpart in the database to compare it to |

## Goals (prioritized)

| Priority | Goal |
|----------|------|
| MUST | `make index-corpus` embeds all 304 chunks and writes them to `chunks`, with `embedding` non-null and 384-dimensional on every row |
| MUST | The run is **idempotent**: running it twice against the same snapshot leaves the same row count and the same content, with no unique-constraint failure |
| MUST | The corpus commit SHA per project is stored in the database and joinable to the rows it produced — the *indexed == verified* assertion becomes a query, not a promise |
| MUST | A **dimension guard**: writing a vector whose length is not the column's 384 fails loudly at the boundary, before Postgres reports it as a type error from inside a batch |
| MUST | `token_count` written to each row is the same number the slice-1 dry run reported for that chunk — the measurement and the stored value cannot diverge silently |
| MUST | `make reindex` cannot leave the index empty on failure: the destructive step and the repopulating step either both land or neither does |
| MUST | `make bootstrap` stops being able to drop a populated `chunks` table without saying so |
| SHOULD | An ADR for whatever the provenance schema turns out to be — it is a data-model change, which AGENTS.md makes architectural by definition |
| SHOULD | Progress output proportionate to a run that loads a model and embeds 304 texts, so a slow first run is distinguishable from a hung one |
| SHOULD | `make index-corpus` refuses to run against a snapshot that fails the inventory staleness check, exactly as the dry run does |
| COULD | Batch size exposed as configuration rather than a literal |
| COULD | A `--dry-run`-equivalent `--verify` mode that compares the database against the snapshot without writing |

## Success criteria (measurable)

- [ ] `make index-corpus` exits 0 and `SELECT count(*) FROM chunks` returns **304**, matching the dry run exactly
- [ ] `SELECT count(*) FROM chunks WHERE embedding IS NULL` returns **0**
- [ ] `SELECT DISTINCT vector_dims(embedding) FROM chunks` returns exactly one row, **384**
- [ ] Running `make index-corpus` a second time with no intervening change exits 0 and leaves **304** rows — not 608, and not an `IntegrityError`
- [ ] The stored corpus SHA is a **40-character** string per project, and matches `MANIFEST.json` for **2** of 2 projects
- [ ] `SELECT count(*) FROM chunks WHERE collection = 'decisions'` equals the ADR chunk count the dry run reports, and `'architecture'` equals the rest; the two sum to **304**
- [ ] Per-row `token_count` equals the dry run's value for the same `(source_project, source_path, chunk_index)` for **304** of 304 rows
- [ ] **0** rows have `token_count > 512`
- [ ] A deliberately mis-dimensioned vector is rejected by the writer's own guard, naming the offending chunk, before any `INSERT` is attempted
- [ ] `make reindex` interrupted after the destructive step leaves either **304** rows or the **pre-existing** row count — never 0
- [ ] `make verify-indexes` runs `sql/99_verify.sql` against a populated table and returns plans that use `idx_chunks_embedding_hnsw`, not a sequential scan

## Acceptance tests

- [ ] Given a fresh snapshot and an empty table, `make index-corpus` populates it and the counts above hold
- [ ] Given a populated table and the same snapshot, a second run is a no-op in effect: same count, same SHAs, no error
- [ ] Given a populated table and a **new** snapshot at a different commit, the run replaces the affected rows and the stored SHA moves to the new commit — no mixture of two commits is queryable as one corpus
- [ ] Given a chunk whose embedding comes back the wrong length, the writer raises and names the chunk, and the transaction leaves no partial rows
- [ ] Given an absent snapshot, `make index-corpus` raises rather than writing an empty index — the dev-log #16 invariant, extended to the writer
- [ ] Given a snapshot that fails the inventory staleness check, `make index-corpus` refuses, matching the dry run
- [ ] Given a `make reindex` that fails partway, `SELECT count(*)` is never 0
- [ ] Given a populated index, one real query embedded with `embed_query` returns its nearest neighbours in under a second and the top hit is a chunk from a plausibly relevant ADR — a sanity check, not a RAGAS score

## Non-goals

Explicitly out of scope for this slice:

- **Retrieval, reranking, generation.** Hybrid search, RRF fusion, the
  cross-encoder and the Claude call are all their own features. This slice ends
  at rows in a table. The one query in the acceptance tests is a smoke test run
  by hand, not a pipeline.
- **The ADR-004 benchmark.** Decided: slice 2 builds on `settings.embedding_model`
  (`BAAI/bge-small-en-v1.5`) as the declared baseline, and ADR-004 stays
  **Planned**. Benchmarking needs a working index and a representative golden
  set; this slice supplies the first, and the second is 5 of 50. Tuning against
  5 questions would produce a number the AGENTS.md boundary would call invented.
- **HNSW parameter tuning.** `m = 16, ef_construction = 64` stand as the
  documented baseline. This slice populates the index; it does not tune it. The
  `EXPLAIN ANALYZE` baseline in `sql/99_verify.sql` becomes *capturable* here,
  which is what ADR-004 will later need.
- **`topic` and `keywords` population.** Both stay `NULL`, as in slice 1. The
  schema already defines `keywords IS NULL` as "extraction did not run", and the
  partial GIN index is already built for the day it does.
- **Canonicalising `adr_id`.** Still a COULD carried from slice 1. Nothing in
  this slice reads it, and normalising it at write time without a decided
  canonical form would bake the wrong form into 304 rows.
- **Langfuse tracing of indexing runs.** Langfuse is scoped to query traces
  (ADR-009). An index run is a batch job, not a user query.
- **Chunking changes.** ADR-007 as amended is implemented and measured. If this
  slice finds itself editing `chunker.py`, that is a signal something upstream
  was wrong, not a task.

## Open questions

- [ ] **Where does the corpus SHA live?** A `corpus_snapshot` table with a
  foreign key from `chunks` normalises it and lets one row describe one fetch;
  a plain column on `chunks` denormalises but keeps every query single-table and
  costs no join. The first models the truth better — a snapshot is an entity with
  a `created_at` and two project SHAs. The second is one migration line. This is
  the ADR's central question and it must be answered before any DDL is written.
- [ ] **Upsert, or replace-by-scope?** `ON CONFLICT (source_project,
  source_path, chunk_index) DO UPDATE` is idempotent per row, but a chunk that
  *disappears* between commits — a file deleted, or a section that now packs into
  fewer chunks — leaves an orphan row the upsert never touches. Deleting by
  `source_project` and reinserting inside one transaction has no orphan problem
  and a brief window where the scope is empty. The acceptance test "no mixture of
  two commits is queryable as one corpus" is the one that decides this.
- [ ] **What makes `make reindex` atomic, given it spans two processes?** The
  truncate could move inside the Python writer's transaction, or `reindex` could
  become a single script invocation with a flag. The current shape — `psql -c`
  then `$(MAKE)` — cannot be made atomic without changing which process owns the
  destruction.
- [ ] **How does `make bootstrap` stop being destructive?** Split the DDL so the
  drops live in a separate `sql/00_reset.sql` that bootstrap does not run; or
  guard on row count and refuse; or leave it and document it loudly. The first is
  cleanest and changes a file slice 1 did not touch.
- [ ] **What happens when the embedding model changes?** The column is
  `VECTOR(384)`. A 768-dim model is a migration, not a config change, and the
  stored rows carry no record of which model produced them. Storing the model
  name beside the SHA would make a model swap detectable rather than a silent
  mixture of two embedding spaces — but it widens the provenance schema this
  slice is already deciding.
- [ ] **Does the first run need network access, and is that acceptable in CI?**
  `tokenizer.py` already warns that a first run fetches the vocabulary from the
  Hub. `sentence-transformers` fetches the full model. Slice 1's integration
  tests were deliberately built to need no network; this slice cannot make the
  same promise without a fixture strategy, and CI has to be told which it is.

## Deferred exit criterion — and a correction to slice 1

Slice 1's DEFINE deferred the WORKFLOW_CONTRACTS BUILD criterion "make eval shows
no regression on golden set", with cause, and closed with: *"The criterion
returns, unmodified, at slice 2."*

**It does not, and that sentence was wrong when it was written.** `make eval`
runs RAGAS, which scores generated answers against retrieved contexts. This
slice builds neither retrieval nor generation — both are explicit non-goals
above, and correctly so. The golden set also still stands at **5 of 50**, so even
a complete pipeline would be scored against a tenth of its intended sample.

Recording this as a correction rather than quietly deferring again, per the
ADR discipline on reversals: the promise is superseded in place, not erased. The
criterion returns when a pipeline exists end to end and the golden set is
populated — that is a condition, not a slice number, and naming a slice number
again would repeat the mistake.

Standing in its place for this slice: the count and provenance assertions above,
the idempotency test, and the hand-run nearest-neighbour smoke check. All are
observable without RAGAS.

## Clarity Score self-check

Rate each 1-5. Total must be >= 12/15 to proceed to Design.

| Dimension | Score | Notes |
|-----------|-------|-------|
| Problem is specific and testable | 5 | The gap is a row count: 304 measured, 0 stored. The three secondary holes were each read out of a specific file — the DDL's leading `DROP`, the Makefile's two-process `reindex`, the absent provenance column — and each has a mechanical test |
| Users are named and their pain is real | 4 | The curator's pain is the sharpest and most present-tense: 45 questions to write with no way to check any of them. Not a 5 for the reason slice 1 gave — two of four rows are consumers, not people |
| Success criteria include numbers | 4 | Ten of eleven are exact counts or dimensions, and 304 is inherited from a measurement rather than estimated. Not a 5: the last criterion ("uses the HNSW index, not a sequential scan") is a plan shape, and at 304 rows the planner may legitimately prefer a sequential scan — which would make the criterion fail for a correct system. It needs restating in DESIGN or dropping |
| **Total** | **13/15** | Above the 12/15 gate |
