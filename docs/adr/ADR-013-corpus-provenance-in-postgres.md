# ADR-013 — Corpus provenance in Postgres, and replace-by-scope indexing

**Status**: Accepted
**Date**: 2026-09-18

## Context

ADR-012 made the corpus snapshot a provenance-bearing artifact on disk: a
`MANIFEST.json` recording, per project, the repo URL, the 40-character commit
SHA, and a sha256 for every extracted file. Its stated purpose is that a score
can name the corpus commit it was measured against.

That chain breaks at the database boundary. `sql/01_schema.sql` gives `chunks`
no column that can hold a commit SHA. The manifest names a commit; the rows name
nothing. The assertion ADR-012 exists to enable — *indexed corpus == verified
corpus* — cannot be written as a query, so the blocking gate at ADR-011 Layer 1
greps a snapshot that nothing proves the index was built from.

`contracts.py` already anticipated this. `CorpusManifest.schema_version` carries
a comment saying it is present from v1 "because slice 2 must store these SHAs
beside the indexed rows, and a format that cannot be versioned cannot be
migrated." The contract was written expecting a schema that was never supplied.

Two further problems are properties of the same gap, and are settled here
because separating them would leave the writer's transaction boundary undecided:

**An index can silently mix two commits.** Without provenance, re-running
indexing after a corpus repo moves updates the rows that changed and leaves
untouched the rows whose source files were deleted or whose chunk count shrank.
The result is a table that is partly commit X and partly commit Y, queryable as
one corpus, with nothing recording that it is not one.

**`make reindex` can empty the index and leave it empty.** `Makefile:77-79` runs
`TRUNCATE chunks;` as a standalone `psql -c`, which commits on its own, and then
invokes `make index-corpus` as a separate process. Any failure after the
truncate — a model that will not load, a vocabulary fetch over the network, an
interrupt — leaves zero rows, with no step that caused it still running. The
target is documented as "(destructive)", which describes its intent and not this
failure mode.

## Decision

**Corpus provenance becomes a first-class table, and indexing replaces whole
project scopes inside one transaction.**

### 1. A `corpus_snapshot` table, at the grain of one project per fetch

One row per `(snapshot, source_project)`. The grain is deliberate: it is the
grain at which indexing replaces, and the grain at which a commit SHA is
meaningful. A snapshot covering two projects produces two rows, which repeats
the manifest's `created_at` across them. That denormalisation is accepted in
preference to a third table whose only purpose would be to hold one timestamp.

The row records the manifest's provenance (repo URL, commit SHA, file count,
manifest `created_at` and `schema_version`) and, in addition, **the embedding
model and dimension that produced the vectors**. The model belongs here because
a model swap is otherwise undetectable: `VECTOR(384)` accepts vectors from any
384-dimensional model, and two models' outputs are not comparable. Without this
column, a mixed embedding space looks exactly like a healthy index.

### 2. `chunks` gains a `snapshot_id` foreign key, with `ON DELETE CASCADE`

Every chunk names the snapshot row it came from. The foreign key is composite —
`(snapshot_id, source_project)` referencing a `UNIQUE (id, source_project)` on
the parent — so a chunk cannot claim a project different from its snapshot's.
Agreement is enforced by the database rather than by the writer remembering.

`chunks.source_project` is retained despite being derivable through the join. It
carries the existing `UNIQUE (source_project, source_path, chunk_index)`
constraint, and every retrieval filter uses it; removing it would put a join in
the hot path of every query to save one column on 304 rows.

### 3. Indexing replaces by scope, not by upsert

For each project in the snapshot, in one transaction: delete that project's
`corpus_snapshot` row — the cascade removes its chunks — then insert the new
snapshot row and all of that project's chunks.

`ON CONFLICT (source_project, source_path, chunk_index) DO UPDATE` was the
alternative and is rejected. It is idempotent per row, but it is blind to rows
that should no longer exist: a source file deleted upstream, or a section that
now packs into four chunks where it once produced six, leaves orphans the upsert
never visits. Those orphans are retrievable, and they are the worst possible
retrievable content — text that is no longer in the corpus, citable with a
source path that no longer contains it.

Replace-by-scope has no orphan case by construction. Its cost is a window in
which a project's rows are absent; that window is inside a transaction, so no
reader observes it.

### 4. `make reindex` and `make index-corpus` collapse into one owner

Because replace-by-scope already deletes and repopulates, `TRUNCATE` is
redundant. The Makefile's two-process shape is deleted: the destructive step
moves inside the writer's transaction, where it belongs. `make reindex` becomes
`index_corpus.py --force`, which differs from `make index-corpus` only in
skipping the short-circuit that declines to re-embed a project already indexed
at the same commit with the same model.

### 5. The drops leave the bootstrap path

`sql/01_schema.sql` opens with `DROP TABLE IF EXISTS chunks CASCADE`, under a
comment reading "Comment out in production migrations" — the hazard was seen,
but the target that runs it, `make bootstrap`, is the documented ordinary way to
start the database. Harmless while the table is always empty; destructive the
moment this ADR is implemented.

The drops move to `sql/90_reset.sql`, which `make bootstrap` does not run,
reached by an explicit `make reset-db`. The `00`–`02` sequence becomes
create-only and idempotent.

## Consequences

**Positive**

- *Indexed == verified* becomes an executable query: compare
  `corpus_snapshot.commit_sha` against `MANIFEST.json` per project. ADR-012's
  purpose reaches the database.
- A mixed-commit index is unrepresentable. Each project's rows descend from
  exactly one snapshot row, and the cascade makes that structural.
- A model swap is detectable, and an index built from two embedding spaces is
  identifiable by a single `SELECT DISTINCT embedding_model`.
- `make reindex` cannot leave an empty index: the delete and the insert share a
  transaction.
- `make bootstrap` becomes safe to run against a populated database.

**Negative**

- A migration exists for a table that has never held a row. Cheap now, and the
  cheapest it will ever be — the reason to do it in this slice.
- The composite foreign key is more machinery than a plain `snapshot_id`. It is
  justified by what it prevents: a chunk whose `source_project` disagrees with
  its snapshot's is exactly the corruption replace-by-scope is designed to make
  impossible, and leaving it to the writer would leave it to a code path.
- Re-indexing one project re-embeds all of its chunks, including unchanged ones.
  At 304 chunks this is seconds. It would not survive a corpus two orders of
  magnitude larger, and that is a known limit, not a hidden one.
- The snapshot's `created_at` and `schema_version` repeat across the two rows of
  one fetch. Accepted in section 1.

**Neutral**

- ADR-004 is untouched and stays **Planned**. This ADR stores which model was
  used; it does not choose one. `settings.embedding_model` remains the declared
  baseline.
- HNSW parameters are untouched. `m = 16, ef_construction = 64` stand.

## Alternatives Considered

**A plain `commit_sha` column on `chunks`.** One migration line, no join, and
every query stays single-table. Rejected: the SHA is a property of a fetch, not
of a chunk, so it would repeat across every row with nothing enforcing that the
repetitions agree. Half a project's rows could carry commit X and half commit Y
and the schema would permit it. The `embedding_model` column would have the same
problem, twice over.

**A `corpus_snapshot` table at the grain of one row per fetch.** More normalised:
one row holds `created_at` and `schema_version` once, with per-project SHAs in a
child table. Rejected as a third table earning its existence with one timestamp,
and it puts a join between a chunk and its own commit SHA — the single most
common provenance question.

**Upsert with a sweep.** `ON CONFLICT DO UPDATE`, followed by deleting rows not
touched by this run. Rejected: it reaches the same end state as replace-by-scope
through two steps that must agree about what "this run" covered, and the sweep is
a second place for the scope definition to drift. AGENTS.md already carries a
boundary against a second declaration of the corpus file set for this reason.

**Leaving `make reindex` as-is and documenting the hazard.** Rejected: the
failure mode is silent and its result — an empty index — is indistinguishable at
a glance from a system that simply has not been indexed yet.
