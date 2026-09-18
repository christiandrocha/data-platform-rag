# DESIGN: Embedding and the pgvector writer

> Implements [DEFINE.md](DEFINE.md), slice 2 of `corpus-indexing`.
> Decision of record: [ADR-013](../../../../docs/adr/ADR-013-corpus-provenance-in-postgres.md).
> Predecessor: [slice 1](../corpus-indexing/BUILD_REPORT.md), merged at `06778d8`.

## Metadata

| Field | Value |
|-------|-------|
| Feature | corpus-indexing-writer (slice 2 of 2) |
| Depends on | [DEFINE.md](DEFINE.md), Clarity Score 13/15 |
| Status | Draft |
| ADR needed | Yes — [ADR-013](../../../../docs/adr/ADR-013-corpus-provenance-in-postgres.md), corpus provenance in Postgres |

## Architecture overview

Slice 1 ends at a list of `Chunk` objects that a dry run prints and discards.
This slice attaches two stages to that point — embed, then write — and gives the
write stage a transaction boundary per project.

```
make index-corpus [--force] [--verify]
      │
      ├─ resolve_snapshot()            ← corpus.py, unchanged
      ├─ read_manifest()               ← corpus.py, unchanged
      ├─ check_inventory()             ← index_corpus.py, promoted to blocking
      │
      └─ for each project in the manifest:
             │
             ├─ short-circuit? ────────→ same commit_sha + same embedding_model
             │                            already in corpus_snapshot, and not
             │                            --force → skip, report "up to date"
             │
             ├─ load_corpus()  ────────→ RawDocument per in-corpus file
             ├─ chunk_document() ──────→ Chunk objects  (ADR-007, unchanged)
             ├─ embed_documents() ─────→ list[list[float]], batched
             ├─ dimension guard ───────→ raise naming the chunk, before any SQL
             │
             └─ BEGIN ─────────────────────────────────────────────┐
                  DELETE FROM corpus_snapshot WHERE project = X    │ one
                     └─ ON DELETE CASCADE removes its chunks       │ transaction
                  INSERT corpus_snapshot → returns snapshot_id     │ per
                  COPY/executemany chunks with that snapshot_id    │ project
                COMMIT ───────────────────────────────────────────┘
```

**New**

- `data_platform_rag/indexer/writer.py` — owns the connection, the transaction,
  and the SQL. The only module in the package that writes to Postgres.
- `sql/03_corpus_snapshot.sql` — the new table, its constraints, and the
  `chunks.snapshot_id` column.
- `sql/90_reset.sql` — the drops, evicted from `01_schema.sql` (ADR-013 §5).
- `docs/adr/ADR-013-corpus-provenance-in-postgres.md`.

**Changed**

- `data_platform_rag/indexer/embedder.py` — the three `NotImplementedError`
  stubs become implementations. The docstrings already specify the behaviour
  (cached `embed_query`, uncached `embed_documents`); they are honoured, not
  rewritten.
- `scripts/index_corpus.py` — gains the real mode. `--dry-run` is untouched and
  keeps its exact current output, because slice 1's measured numbers are the
  regression baseline this slice is checked against.
- `data_platform_rag/contracts.py` — `IndexedSnapshot` and `IndexRunReport`.
- `sql/01_schema.sql` — leading `DROP` statements removed; `chunks` unchanged
  otherwise.
- `Makefile` — `index-corpus` gains flags, `reindex` becomes one process,
  `reset-db` added.
- `docs/adr/index.md` — the ADR-013 row.
- `AGENTS.md` — the `reindex` and Makefile-target-count lines.

**Unchanged**: `chunker.py`, `corpus.py`, `loader.py`, `tokenizer.py`,
`fetch_corpus.py`, `verify_adversarials.py`, `audit_questions.py`. If this slice
finds itself editing `chunker.py`, something upstream was wrong (DEFINE non-goal).

## Data contracts

### `corpus_snapshot` (new table, `sql/03_corpus_snapshot.sql`)

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL PK` | |
| `source_project` | `TEXT NOT NULL` | `CHECK` against the two corpus projects |
| `repo_url` | `TEXT NOT NULL` | from the manifest |
| `commit_sha` | `CHAR(40) NOT NULL` | `CHECK (commit_sha ~ '^[0-9a-f]{40}$')` |
| `file_count` | `INT NOT NULL` | manifest file count for this project |
| `manifest_created_at` | `TIMESTAMPTZ NOT NULL` | repeats across the fetch's two rows, per ADR-013 §1 |
| `manifest_schema_version` | `INT NOT NULL` | so a format migration is detectable |
| `embedding_model` | `TEXT NOT NULL` | e.g. `BAAI/bge-small-en-v1.5` |
| `embedding_dim` | `INT NOT NULL` | `CHECK (embedding_dim = 384)` for v1 |
| `chunk_count` | `INT NOT NULL` | what this run wrote; checkable against `count(*)` |
| `indexed_at` | `TIMESTAMPTZ NOT NULL DEFAULT NOW()` | |

Constraints:

- `UNIQUE (source_project)` — one live snapshot per project. Replace-by-scope
  deletes before inserting, so this is the invariant that makes a mixed-commit
  index unrepresentable rather than merely unlikely.
- `UNIQUE (id, source_project)` — exists solely as the target of the composite
  foreign key below.

### `chunks` (altered)

```sql
ALTER TABLE chunks ADD COLUMN snapshot_id BIGINT NOT NULL;
ALTER TABLE chunks ADD CONSTRAINT fk_chunks_snapshot
    FOREIGN KEY (snapshot_id, source_project)
    REFERENCES corpus_snapshot (id, source_project)
    ON DELETE CASCADE;
CREATE INDEX idx_chunks_snapshot ON chunks (snapshot_id);
```

The composite form is what enforces that a chunk cannot claim a project
different from its snapshot's (ADR-013 §2). Everything else about `chunks` —
including `UNIQUE (source_project, source_path, chunk_index)` and the generated
`content_tsv` — is untouched.

### `contracts.py` additions

```python
class IndexedSnapshot(BaseModel):
    """One project's provenance row, as written to corpus_snapshot."""
    model_config = ConfigDict(frozen=True)

    source_project: SourceProject
    repo_url: AnyUrl
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    file_count: int = Field(gt=0)
    manifest_created_at: datetime
    manifest_schema_version: int = Field(ge=1)
    embedding_model: str = Field(min_length=1)
    embedding_dim: int = Field(gt=0)
    chunk_count: int = Field(ge=0)


class IndexRunReport(BaseModel):
    """What one `make index-corpus` invocation did. The CLI's return value."""
    model_config = ConfigDict(frozen=True)

    snapshot_root: str
    written: list[IndexedSnapshot]
    skipped: list[SourceProject]      # short-circuited, already current
    embedding_model: str
    duration_seconds: float = Field(ge=0.0)
```

Per the contract discipline, nothing crosses the writer boundary as a `dict`.
`IndexRunReport` is also what `--verify` returns, with `written` empty.

## Interfaces

### `indexer/writer.py`

```python
def write_project(
    conn: psycopg.Connection,
    snapshot: IndexedSnapshot,
    chunks: list[Chunk],
    embeddings: list[list[float]],
) -> int:
    """Replace one project's scope. Returns rows written. One transaction."""

def current_snapshots(conn: psycopg.Connection) -> dict[SourceProject, IndexedSnapshot]:
    """What is indexed now. Feeds the short-circuit and `--verify`."""
```

`write_project` takes an open connection rather than creating one: the caller
owns the lifetime, and a test can hand it a connection inside a rolled-back
outer transaction. `chunks` and `embeddings` are parallel lists, and the
dimension guard runs over them before the transaction opens — a guard inside the
transaction would mean a rollback where a refusal would do.

### `indexer/embedder.py`

Signatures already exist and do not change. `get_model()` loads
`settings.embedding_model` through `sentence_transformers.SentenceTransformer`;
`embed_documents` batches at `settings.embedding_batch_size` and calls
`model.encode(..., normalize_embeddings=True)`.

Normalisation is not cosmetic: `sql/02_indexes.sql` builds the HNSW index with
`vector_cosine_ops`, and the ADR-004 comment records cosine as matching
bge-small's training objective. Normalising at write time keeps cosine distance
and inner product equivalent, which is what lets a later retrieval change swap
operators without a reindex.

### CLI and config

| Addition | Where | Behaviour |
|----------|-------|-----------|
| `--force` | `index_corpus.py` | Re-embed even if the commit and model already match |
| `--verify` | `index_corpus.py` | Compare database against manifest, write nothing, exit non-zero on drift |
| `--batch-size` | `index_corpus.py` | Overrides the configured default |
| `embedding_batch_size` | `config.py` | `Field(default=32, ge=1, le=512)` |
| `embedding_dim` | `config.py` | `Field(default=384, ge=1)` — the guard's expectation, so the value is named once |
| `make reset-db` | `Makefile` | Runs `sql/90_reset.sql`. The only path to a drop |

`make reindex` becomes `$(PYTHON) scripts/index_corpus.py --force`. The
`TRUNCATE`-then-`$(MAKE)` pair is deleted (ADR-013 §4).

## Retrieval and RAG-specific concerns

- [x] **Does this affect chunking?** No. ADR-007 as amended is implemented and
  measured; `chunker.py` is on the unchanged list. The dry run's output is the
  baseline this slice is verified against, so changing it would destroy the
  check.
- [x] **Does this touch the HNSW index? Reindex needed?** The index is created
  by `sql/02_indexes.sql` and its parameters are untouched. It has never held a
  row, so there is nothing to reindex — this slice is the first population. One
  consequence worth stating: building the index before inserting means HNSW is
  built incrementally per insert rather than in bulk. At 304 rows the difference
  is not measurable, and keeping the existing bootstrap order avoids an ordering
  dependency that would only exist to save milliseconds.
- [x] **Does this change the query pattern?** It adds `snapshot_id` to the table
  but no v1 retrieval query filters on it — provenance is asserted by
  `--verify`, not by the hot path. The retrieval queries in `sql/99_verify.sql`
  are unchanged in shape; what changes is that they can finally be run against
  rows.
- [x] **Does this change RAGAS metrics? Regression test needed?** No metric
  exists to regress against. No retrieval and no generation are built here, and
  the golden set is 5 of 50. See *Deferred exit criterion*, below.

**Restating one DEFINE success criterion.** DEFINE's final criterion — that
`make verify-indexes` shows plans using `idx_chunks_embedding_hnsw` rather than a
sequential scan — was flagged in its own Clarity self-check and is **replaced
here**. At 304 rows the planner may legitimately prefer a sequential scan, which
would fail the criterion for a correct system. The replacement:

> `make verify-indexes` runs against a populated table, and its `EXPLAIN ANALYZE`
> output is captured as the regression baseline. The HNSW index is separately
> proven *usable* by forcing it with `SET LOCAL enable_seqscan = off` and
> confirming the plan switches and returns the same rows.

That measures what the criterion meant — the index works — without asserting a
planner choice that small-table statistics make arbitrary.

## Alternatives considered

The data-model alternatives (a plain `commit_sha` column, a one-row-per-fetch
snapshot table, upsert-plus-sweep, leaving `reindex` as-is) are argued and
rejected in ADR-013's *Alternatives Considered*. Not repeated here.

Two alternatives are local to this DESIGN:

- **`COPY` instead of `executemany` for the insert.** `COPY` is materially
  faster and is the right tool at scale. Rejected for v1: 304 rows insert in well
  under a second either way, `executemany` with `psycopg`'s pgvector adapter is
  the more legible code, and `COPY` would need explicit vector text formatting
  that is a second place to get the dimension wrong. Revisit if the corpus grows
  by an order of magnitude.
- **Embedding inside the transaction, streaming per batch.** Lower peak memory,
  and a failure loses less work. Rejected: it holds a write transaction open
  across a model call that may block on a network fetch of the vocabulary, and
  `embed → guard → write` keeps every failure that is not a database failure
  outside the database. 304 × 384 floats is under 500 KB.

## Test plan

**Unit** (no database, no model, no network)

- `test_writer.py` — the dimension guard: a wrong-length vector raises naming
  the offending chunk's `source_path` and `chunk_index`; a correct batch passes.
- `test_writer.py` — parallel-list invariant: `len(chunks) != len(embeddings)`
  raises rather than silently zipping to the shorter.
- `test_embedder.py` — `embed_query` returns a tuple, not a list, and the same
  call twice returns the identical object (the `lru_cache` contract its docstring
  states); `embed_documents` is not cached.
- `test_contracts.py` — `IndexedSnapshot` rejects a 39-character SHA, a negative
  `chunk_count`, and an unknown `source_project`.
- Both embedder tests inject a fake encoder, so the suite stays offline.

**Integration** (Postgres via docker-compose; fake embedder, deterministic vectors)

- Populate from a fixture snapshot: row counts, `vector_dims` = 384, zero NULL
  embeddings, `chunk_count` on the snapshot row equals `count(*)` of its chunks.
- Idempotency: run twice, assert the same row count and no `IntegrityError`.
- Replace-by-scope: index commit A, then commit B where one file is deleted —
  assert no row survives from A, and `SELECT DISTINCT commit_sha` returns one
  value.
- Cascade: `DELETE FROM corpus_snapshot WHERE source_project = X` removes
  exactly that project's chunks and leaves the other project's intact.
- Composite FK: an `INSERT` into `chunks` whose `source_project` disagrees with
  its `snapshot_id`'s project is rejected by the database.
- Atomicity: a writer that raises mid-transaction leaves the pre-existing row
  count, never 0. Asserted by injecting a failure after the delete.
- Absent snapshot and stale inventory: both refuse before any write.

**Manual verification** (the real model, once, recorded in BUILD_REPORT)

- `make bootstrap && make fetch-corpus && make index-corpus` — assert **304**
  rows, matching the dry run exactly, and the per-row `token_count` equality
  check across all 304.
- `make index-corpus` again — reports both projects skipped, writes nothing.
- `make index-corpus --force` — rewrites, still 304.
- `make verify-indexes` — capture the plans as the new baseline; run the
  `enable_seqscan = off` check described above.
- Nearest-neighbour smoke check: embed one golden-set question with
  `embed_query`, retrieve the top 5, and read them. A sanity check on whether
  the pipeline is wired to the right end of the corpus — **not** a score, and no
  number from it goes anywhere near the README.

## Rollout plan

**Migration order.** Against an existing local database:

1. `make reset-db` (new) — or accept that `chunks` is empty everywhere today, in
   which case a plain `make bootstrap` is equivalent. The table has never held a
   row, so this migration has no data to preserve. That is precisely why ADR-013
   takes it in this slice.
2. `sql/00_extensions.sql`, `01_schema.sql` (now drop-free), `02_indexes.sql`,
   `03_corpus_snapshot.sql` — in that order. `03` must follow `01` because it
   alters `chunks`.
3. `make fetch-corpus`, then `make index-corpus`.

**Feature flag.** None. Nothing user-visible ships in this slice: the Streamlit
app has no retrieval path to expose the rows through.

**Rollback.** Reverting the commit restores a `chunks` table without
`snapshot_id` and an `index_corpus.py` that refuses to run. Any rows written
under the new schema become unreadable by the old code — which is acceptable
because they are reproducible from the snapshot by construction, and the snapshot
is the durable artifact. `make reset-db && make bootstrap` returns to a clean
pre-slice state in two commands.

**CI.** `ci.yml` needs the embedding model to run the integration tests. The
decision below keeps CI offline by injecting a fake embedder there; the real
model runs in manual verification only, until a later slice needs it in CI and
can add a cache step deliberately.

## Open questions

Carried from DEFINE, all resolved or explicitly deferred:

- [x] **Where does the corpus SHA live?** `corpus_snapshot` table at one row per
  project, composite FK from `chunks`. ADR-013 §1–2.
- [x] **Upsert or replace-by-scope?** Replace-by-scope, one transaction per
  project. ADR-013 §3.
- [x] **What makes `make reindex` atomic across two processes?** It stops
  spanning two. The destructive step moves inside the writer's transaction and
  `reindex` becomes `--force`. ADR-013 §4.
- [x] **How does `make bootstrap` stop being destructive?** The drops move to
  `sql/90_reset.sql`, reached only by `make reset-db`. ADR-013 §5.
- [x] **What happens when the embedding model changes?** `embedding_model` and
  `embedding_dim` are recorded on the snapshot row, and a model change is part of
  the short-circuit key — so changing the model causes a re-embed rather than a
  silent mixture of two embedding spaces. A dimension change remains a migration,
  now a detectable one.
- [x] **Does the first run need network, and is that acceptable in CI?**
  Resolved: unit and integration tests inject a fake embedder and stay offline,
  matching slice 1's no-network test posture. The real model runs in manual
  verification. CI does not download a model in this slice.
- [ ] **Deferred: canonical `adr_id`.** Still a COULD, still unread by anything
  in this slice, and normalising at write time without a decided canonical form
  would bake the wrong form into 304 rows. Carried forward unchanged.
- [ ] **Deferred: `topic` and `keywords` stay `NULL`.** As in slice 1. The
  partial GIN index already exists for the day extraction runs.

## Deferred exit criterion

WORKFLOW_CONTRACTS requires, for BUILD, "make eval shows no regression on golden
set". **Deferred again, and DEFINE records why slice 1's promise that it would
return here was wrong**: RAGAS scores generated answers against retrieved
contexts, and this slice builds neither retrieval nor generation. The golden set
is also 5 of 50.

The criterion returns when the pipeline exists end to end and the golden set is
populated — a condition, not a slice number. Standing in its place: the count,
dimension, provenance, idempotency and atomicity assertions in the test plan,
every one observable without RAGAS.
