# BUILD REPORT: Embedding and the pgvector writer

## Metadata

| Field | Value |
|-------|-------|
| Feature | corpus-indexing-writer (slice 2 of 2) |
| DEFINE | [DEFINE.md](DEFINE.md) |
| DESIGN | [DESIGN.md](DESIGN.md) |
| ADR | [ADR-013](../../../../docs/adr/ADR-013-corpus-provenance-in-postgres.md) |
| Start date | 2026-09-18 |
| End date | 2026-09-18 |
| PR | [#1](https://github.com/christiandrocha/data-platform-rag/pull/1), merged by rebase 2026-09-18 |

## What was built

**New**

- `data_platform_rag/indexer/writer.py` — the only module in the package that
  writes to Postgres. Replace-by-scope, one transaction per project, with the
  dimension guard running *before* the transaction opens.
- `sql/03_corpus_snapshot.sql` — the provenance table, the composite foreign key,
  and `chunks.snapshot_id`.
- `sql/90_reset.sql` — the drops, evicted from the bootstrap path.
- `docs/adr/ADR-013-corpus-provenance-in-postgres.md`, plus its index row.
- `tests/integration/conftest.py` — a dedicated `_test` database, built from the
  same `sql/` files as production.

**Changed**

- `indexer/embedder.py` — three `NotImplementedError` stubs became
  implementations. The docstrings' stated contracts (cached `embed_query`
  returning a tuple, uncached `embed_documents`, normalised vectors) were
  honoured rather than rewritten.
- `scripts/index_corpus.py` — real mode, `--force`, `--verify`, `--batch-size`.
  `--dry-run` is behaviourally untouched; its 304-chunk output is the baseline
  the real run is checked against.
- `contracts.py` — `IndexedSnapshot` (with `is_current_for`, the short-circuit
  key) and `IndexRunReport`.
- `config.py` — `embedding_batch_size`, `embedding_dim`.
- `sql/01_schema.sql` — leading `DROP`s removed, `CREATE TABLE IF NOT EXISTS`.
- `sql/02_indexes.sql` — 8 indexes made idempotent.
- `sql/99_verify.sql` — two pre-existing defects fixed, two sections added. See
  *What deviated*, items 5 and 6.
- `Makefile` — `COMPOSE` variable, `reset-db`, `index-corpus-verify`, `reindex`
  collapsed to one process, `bootstrap` runs `03`.
- `AGENTS.md` — commands, target count (14 → 25), and two new boundaries.
- `indexer/chunker.py`, `indexer/corpus.py` — bandit suppressions only, no logic.

**Tests**: 40 added (91 → **131**). `tests/unit/test_writer.py` (6),
`tests/unit/test_embedder.py` (10), `tests/unit/test_contracts.py` (+13),
`tests/integration/test_writer_postgres.py` (11).

**Measured against the real corpus** at `sdd-kafka-databricks@f1295df9` and
`sdd-kafka-snowflake-2@82a2e269`: 47 files, **304 chunks → 304 rows** (149 + 155),
all 384-dimensional, in 74–88 s per full run.

## What deviated from design

1. **`COMPOSE ?= docker compose` added to the Makefile.** Not in DESIGN. Every
   container target invoked `docker-compose`, the standalone binary, which does
   not exist on a machine carrying only the CLI plugin — `make bootstrap` failed
   with "command not found" before this slice could run at all. Same shape and
   same fix as commit `11fe300` (`python` → `$(PYTHON)`), and overridable for the
   opposite case.

2. **`embed_documents` gained a `batch_size` parameter.** DESIGN had the CLI read
   `--batch-size` into a modified `Settings` copy. That silently does nothing:
   `get_settings()` is an `lru_cache` singleton, so the embedder never sees a
   caller's copy. Caught by writing the test, not by running the code — the flag
   was accepted and ignored. Now an explicit parameter, with two tests pinning
   both the override and the fallback.

3. **The integration fixture destroyed the local index, and was rebuilt.** The
   first version truncated whatever `DATABASE_URL` pointed at. On this machine
   that is the real database, so `make test` silently deleted the 304 rows
   `make index-corpus` had just written — discovered only when a later
   `make verify-indexes` reported `rows=0`. The fixture now derives a
   `<configured>_test` database, creates it on demand, and builds it from the
   same `sql/` files; it also refuses to run if `DATABASE_URL` already ends in
   `_test`. Isolation was then *proved*, not assumed: 304 rows before a full
   suite run, 131 tests pass, 304 rows after.

4. **`make lint` ran to completion for the first time, and bandit had findings.**
   Slice 1 recorded bandit as "unverified, not failing". Verified now: three
   MEDIUM findings, all false positives, all suppressed with justification —
   `writer.py` B608 (an f-string interpolating a module-level literal tuple, every
   value still bound through `%s`), `corpus.py` B108 (the ADR-012 `/tmp` path,
   which already carried a `# noqa: S108` bandit cannot read), and
   `chunker.py` B610 (a local callable named `extra`, matched against Django's
   `QuerySet.extra()`). Each was confirmed load-bearing by removing it and
   watching the finding return. Two of the three are in slice-1 code.

5. **`sql/99_verify.sql` probed a row that cannot exist.** Sections 4 and 5 took
   their probe vector from `WHERE id = 1`. `chunks.id` is `BIGSERIAL` and
   replace-by-scope deletes and reinserts, so the sequence never revisits 1 —
   after the first reindex the subquery returned NULL and the "regression
   baseline" measured nothing. Now `ORDER BY id LIMIT 1`. Pre-existing; invisible
   until there were rows to run it against.

6. **`SET LOCAL` outside a transaction is a no-op.** Section 4 set
   `hnsw.ef_search = 40` bare, which only emits a warning, so that baseline had
   never actually been measured at the setting it claimed. Wrapped in
   `BEGIN`/`COMMIT`. Pre-existing, same cause as item 5.

7. **The DEFINE criterion about HNSW vs sequential scan was replaced, as DESIGN
   said it would be — and the replacement was the right call.** At 304 rows the
   planner picks `Seq Scan` for the dense baseline, exactly as predicted. The
   index is proven usable instead: forced with `enable_seqscan = off` it reports
   `Index Scan using idx_chunks_embedding_hnsw` and returns the *same five ids*
   (`348,357,362,363,498`) in 0.315 ms against 0.616 ms. Both checks now live in
   `sql/99_verify.sql` as sections 4 and 6.

8. **`_INSERT_CHUNK` is built in three statements, not one expression.** Purely
   to give bandit a single physical line to mark; implicit string concatenation
   made it report the same finding on two lines and accept a suppression on
   neither.

## RAGAS delta

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Faithfulness | — | — | n/a |
| Context Precision | — | — | n/a |
| Answer Relevance | — | — | n/a |
| Context Recall | — | — | n/a |
| Fallback rate | — | — | n/a |

**Not measured, and not measurable.** RAGAS scores generated answers against
retrieved contexts. This slice builds neither retrieval nor generation — both
are explicit DEFINE non-goals — and the golden set stands at 5 of 50. `make eval`
was not run because there is nothing for it to run against.

DEFINE records the correction in full: slice 1 promised this criterion would
"return, unmodified, at slice 2", and that promise was wrong when written. Its
return is now tied to a condition — a pipeline that exists end to end and a
populated golden set — rather than to a slice number.

No number is entered above, per the AGENTS.md boundary against invented RAGAS
scores.

**What was run instead**, and is not a score: a nearest-neighbour smoke check on
the first three golden-set questions. q001 (Snowpipe Streaming) returns
`0029_snowpipe_streaming_as_the_ingestion_path.md [Alternatives considered]` at
cosine 0.846 — the right ADR, the right section. q002 (pipeline unification)
returns `001_databricks_vs_snowflake.md` above `006_lakeflow_migration.md`,
which is plausible but not the anchor ADR a curator would name. Read as evidence
that the pipeline is wired to the right end of the corpus, and as an early hint
that dense-only retrieval will need the hybrid and rerank stages it is designed
to get. Nothing here goes near the README.

## Known gaps at merge time

**Non-blocking**

- **`pytest-asyncio` is still not installed**, so every run warns
  `Unknown config option: asyncio_mode`. Pre-existing; no async test exists yet.
- **Bandit emits `nosec encountered, but no failed test` warnings** for
  suppressions that demonstrably work. Bandit reports the finding's line and
  counts the marker's line differently. Cosmetic; `make lint` exits 0.
- **`yamllint` reports line-length errors** in `docs/golden-set/`. Pre-existing,
  and the Makefile already ends that step with `|| true`, so it does not block.
- **Re-indexing one project re-embeds all of its chunks**, including unchanged
  ones. 74–88 s at 304 chunks. Named as a known limit in ADR-013's Consequences,
  not a hidden one.
- **The first run needs network access** for the model weights, as DESIGN
  accepted. Tests do not: every test injects a fake encoder or uses fixture repos.
  CI downloads no model in this slice.
- **`adr_id` is still not canonicalised**, and **`topic` and `keywords` are still
  `NULL`** — both carried forward from slice 1 unchanged, both deliberate.
- **`.venv/` was created to run any of this.** The repo declares its dependencies
  but has no setup step, and this machine's Python is PEP 668 externally managed.
  Gitignored, so nothing is committed; worth a `make venv` target eventually.

**Not a gap, recorded because it looks like one**: `chunks` carries both
`source_project` and a join to `corpus_snapshot`. The redundancy is deliberate
and argued in ADR-013 §2 — it holds the existing unique constraint and keeps a
join out of every retrieval filter.

## Verification

- [x] `make lint` — **clean, exit 0**. ruff (3 trees), yamllint, bandit **0
      issues**. First completion in the project's history
- [x] `make test` — **131 passed** (91 before this feature)
- [x] `make bootstrap` — runs `00`–`03`; run twice, second run reports
      `already exists, skipping` throughout and destroys nothing
- [x] `make fetch-corpus` — 2 projects, 47 files, same commits as slice 1
- [x] `make index-corpus-dry` — **304 chunks**, largest 500, identical to slice 1
- [x] `make index-corpus` — **304 rows** (149 + 155), 0 NULL embeddings, exactly
      one distinct `vector_dims` = **384**, 0 rows over the 512-token window
- [x] **Per-row equality against the chunker** — all 304 rows match on
      `token_count` *and* `content`; 0 keys absent in either direction
- [x] Collections: **159 decisions + 145 architecture = 304**
- [x] Idempotency — second `make index-corpus` skips both projects, writes 0,
      leaves **304** rows and no `IntegrityError`
- [x] `make reindex` — re-embeds and rewrites, still **304** rows, 2 snapshot rows
- [x] `make index-corpus-verify` — **`✓ indexed corpus == verified corpus`**,
      both SHAs matching `MANIFEST.json`. ADR-012's purpose reaches the database
- [x] Test isolation — 304 rows before a full suite run, **304 after**
- [x] `make verify-indexes` — plans captured as the new baseline (below)
- [ ] `make eval` — **not applicable**, no retrieval and no generation exist

### Query plan baseline (2026-09-18, 304 rows)

Index sizes: `idx_chunks_embedding_hnsw` 616 kB, `idx_chunks_content_tsv_gin` 672 kB.

**Section 4 — dense-only.** The planner chooses a sequential scan, which is
correct at this scale and is why the DEFINE criterion was replaced:

```
Limit  (actual time=0.554..0.555 rows=5 loops=1)
  InitPlan 1 (returns $0)
    ->  Index Scan using chunks_pkey on chunks chunks_1 (actual time=0.003..0.003 rows=1)
  ->  Sort  (actual time=0.553..0.554 rows=5 loops=1)
        Sort Key: ((chunks.embedding <=> $0))
        Sort Method: top-N heapsort  Memory: 36kB
        ->  Seq Scan on chunks  (actual time=0.057..0.498 rows=159 loops=1)
              Filter: (collection = 'decisions'::text)
              Rows Removed by Filter: 145
Execution Time: 0.616 ms
```

**Section 5 — hybrid.** The sparse half *does* use its index:

```
->  Bitmap Heap Scan on chunks chunks_1  (actual time=0.902..0.935 rows=4 loops=1)
      Recheck Cond: (content_tsv @@ '''debezium'' & ''cdc'' & ''snowflak'''::tsquery)
      Heap Blocks: exact=10
      ->  Bitmap Index Scan on idx_chunks_content_tsv_gin (actual time=0.026..0.026 rows=17)
Execution Time: 0.727 ms
```

**Section 6 — HNSW proven usable** (`enable_seqscan = off`), same five ids as
section 4, twice as fast:

```
Limit (actual time=0.301..0.315 rows=5 loops=1)
  ->  Index Scan using idx_chunks_embedding_hnsw on chunks (actual time=0.287..0.299 rows=5 loops=1)
        Order By: (embedding <=> $0)
Execution Time: 0.315 ms
```

**Section 7 — provenance:**

```
    source_project     |                commit_sha                | chunk_count |    embedding_model
-----------------------+------------------------------------------+-------------+------------------------
 sdd-kafka-databricks  | f1295df9cb3db1202ee9e70b96faf6667dfe3be8 |         149 | BAAI/bge-small-en-v1.5
 sdd-kafka-snowflake-2 | 82a2e269d467de189daecf5d0bacf139633cdb11 |         155 | BAAI/bge-small-en-v1.5
```
