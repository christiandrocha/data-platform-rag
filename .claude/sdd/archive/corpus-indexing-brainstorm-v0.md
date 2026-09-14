<!-- ARCHIVED — pre-reordering draft. Do not treat as current. -->

> **Archived 2026-09-14 — draft written under the wrong feature order.**
>
> This brainstorm was written on the assumption that `corpus-indexing` was the
> first BUILD feature. It is not. `docs/PRE_BUILD_VALIDATION.md` Section 5E names
> **golden-set curation** as the first BUILD feature, and ADR-004's decision rule
> cannot run without the full 50-question set. The corrected order is:
>
> 1. `golden-set-curation` — 50 questions with expected sources
> 2. *Between features*: run the ADR-004 benchmark against the golden set using a
>    preliminary parameterised pipeline; promote ADR-004 from Planned to Accepted
>    with the winning dimension
> 3. `corpus-indexing` — pipeline with the dimension settled
> 4. `retrieval`, `generation`, `langfuse`, `ui`
>
> **Carried forward as already-established, not to be re-litigated:** Option 1
> (model-agnostic pipeline; the ADR-004 benchmark becomes a consumer of the
> pipeline rather than a blocker on it) is the approved emerging preference for
> `corpus-indexing`. When the Feature 2 brainstorm reopens, it starts there.
>
> Note that step 2 above partly dissolves the circular dependency this draft was
> written to solve — the preliminary parameterised pipeline *is* Option 1, run
> early. The Open Questions section below survives the reordering intact and is
> the most reusable part of this file.

---

# BRAINSTORM: corpus-indexing

> Free exploration. No commitments. No commits from this file alone.

## Date
2026-09-14

## Prompt

First BUILD-phase feature after Phase 0 closed (commit `d0bf569`). The job:
clone the two corpus repos, load their source materials, chunk them per ADR-007,
embed them, and write them into the `chunks` table in pgvector — idempotently,
with the clone deleted afterwards.

What triggered the exploration is not the pipeline itself, which is fairly
conventional, but a **circular dependency** discovered while writing ADR-004:

- ADR-004 decides the embedding model by benchmarking three candidates against
  the golden set, measuring RAGAS Context Recall.
- Running that benchmark requires indexing the corpus three times.
- Indexing requires this feature to exist.
- This feature would normally be designed against a decided embedding dimension,
  because `sql/01_schema.sql` hardcodes `VECTOR(384)`.

Something has to give. The options below are mostly about *which* thing gives.

A second trigger: three decisions this feature depends on are in different
states — ADR-007 (chunking) is Accepted and fully specified, ADR-004 (embedding
+ HNSW) is Planned, and the **collection mapping rule does not exist anywhere**
(see Open Questions).

## Options considered

### Option 1: Model-agnostic pipeline; the benchmark becomes a consumer

The indexing pipeline takes the embedding model and target dimension as
parameters rather than constants. `make index-corpus` runs it with
`settings.embedding_model`. ADR-004's benchmark is a thin script that calls the
same pipeline three times against three throwaway tables.

- **Pros**
  - Dissolves the circular dependency instead of working around it. The
    benchmark stops being a blocker and becomes a caller.
  - The "reindex after a model change" path from ADR-004's Consequences is
    exercised from day one rather than discovered during a migration.
  - Parameterising the dimension is a handful of lines, not an architecture.
- **Cons**
  - The benchmark path cannot use the production table, since `VECTOR(384)` is
    fixed in DDL. Needs templated DDL or per-run benchmark tables.
  - Slightly more surface in v1 than a hardcoded pipeline.

### Option 2: Ship on the `bge-small` baseline; treat ADR-004 as a later migration

Build the pipeline hardcoded to `bge-small-en-v1.5` / 384 dims. Get the corpus
indexed and the system end-to-end runnable. Run ADR-004's benchmark afterwards
as its own feature, paying the five-step migration cost if a different model wins.

- **Pros**
  - Simplest possible v1, and the fastest route to a system that can be measured
    at all. Nothing in this project is measurable until the corpus is indexed.
  - `bge-small` may well win on the deployment gate anyway (ADR-004 expects
    `bge-large` to fail the Streamlit memory ceiling).
- **Cons**
  - Pays the migration cost with certainty if the winner is not `bge-small`,
    rather than with probability.
  - Contradicts ADR-004's explicit sequencing: HNSW tuning runs only after the
    model is fixed, precisely so the tuning is not thrown away.

### Option 3: Benchmark-first — throwaway spike, then the real feature

Build a minimal indexing spike sufficient to run ADR-004's benchmark, decide the
model, then build `corpus-indexing` properly against the decision.

- **Pros**
  - Honours ADR-004's sequencing literally. The real feature is written once,
    against a settled dimension.
- **Cons**
  - Two implementations of the same thing, and throwaway spikes reliably become
    load-bearing.
  - The benchmark needs the golden set to score against, and the golden set
    currently holds 5 of its 50 questions. The spike would block on curation
    anyway — so it buys nothing that Option 1 does not.

### Option 4: Split into `corpus-ingestion` (load + chunk) and `corpus-embedding` (embed + write)

Recognise that loading and chunking are model-independent and fully specified by
ADR-007, while embedding and writing are the parts entangled with ADR-004. Ship
the first half now, the second after the model decision.

- **Pros**
  - Chunking is the riskiest logic in the feature — the ADR-007 split hierarchy,
    the preamble assembly, the 512-token assertion — and it is testable with no
    database and no model loaded.
  - Forces the dev-log item #1 resolution (`Chunk` vs `ChunkMetadata`) early,
    since it sits exactly on the seam between the two halves.
- **Cons**
  - No end-to-end value until the second half lands. A chunker with nothing to
    write to is hard to validate against anything real.
  - Two features to track through six phases each.

## Discarded early

- **A dedicated vector DB (Pinecone/Qdrant/Weaviate)** — ADR-001, settled.
- **Indexing this repo as a corpus source** — hard AGENTS.md boundary; the
  docstring claiming otherwise was removed in Phase 0.
- **Keeping the `/tmp` clone around to speed up re-indexing** — AGENTS.md is
  explicit: clone, extract, index, delete.
- **Committing embedding fixtures as JSON for tests** — AGENTS.md boundary.
  Tests use a fake embedder returning deterministic vectors instead.
- **Incremental ingestion via GitHub webhook** — README Roadmap v2; its trigger
  ("source projects gain regular contributors") has not fired.
- **Parallelising the embedding across processes** — ~200 chunks. A progress bar
  would take longer to write than the time it saves.

## Emerging preference

**Option 1**, with Option 4's ordering used as the internal build sequence rather
than as a feature split.

Parameterising the model is a small, contained cost that converts the central
blocker into an ordinary dependency: ADR-004's benchmark stops waiting on this
feature and starts consuming it. Option 2 is tempting for speed, but it bets the
migration cost on a coin-flip that ADR-004 was explicitly written to avoid
flipping. Option 3 pays for two implementations to buy sequencing that Option 1
gets for free.

Building load → chunk first (Option 4's insight) without formally splitting the
feature keeps the riskiest logic testable early while still delivering one
end-to-end capability.

**What would change our mind:** if templated DDL for benchmark tables turns out
to be genuinely awkward under psycopg3, Option 2 becomes the pragmatic answer —
index on the baseline, accept the migration risk, and let ADR-004 run against a
copy of the production table instead.

## Open questions for DEFINE

1. **The collection mapping rule does not exist.** ADR-002 decides how
   collections are *stored* (one table, `CHECK` on two values) but nothing in the
   repo says how a source file becomes `decisions` versus `architecture`.
   `loader.py::RawDocument` carries a `collection` field with no rule behind it.
   Candidates: map from `source_type` (adr → decisions, everything else →
   architecture), map from path, or derive from content. This needs deciding
   before any chunk is written, and it may deserve its own ADR.
2. **`Chunk` vs `ChunkMetadata`** — dev log item #1, carried over from Phase 0.
   Delete `Chunk` and emit `ChunkMetadata` directly (closer to ADR-010), or keep
   it internal with a test asserting field-set parity.
3. **Idempotency semantics.** `UNIQUE (source_path, chunk_index)` supports upsert,
   but ADR-007 notes that reformatting a source ADR shifts `chunk_index` and
   orphans rows. `make reindex` already truncates. Is upsert worth building, or
   is truncate-and-rebuild the honest primitive at ~200 chunks?
4. **Where `keywords` extraction lives** — chunker or a separate enrichment pass.
   The field landed in Phase 0 with no producer.
5. **Benchmark tables at non-384 dimensions** — the mechanism Option 1 depends on.
6. **Golden set is 5 of 50 questions.** PRE_BUILD_VALIDATION Section 5E names
   golden-set curation as the *first* BUILD feature, and ADR-004's decision rule
   cannot run without it. Sequencing question that outlives this feature.

## Next step
- [x] Write DEFINE if a clear direction emerged
- [ ] Or park with `status: Parked` and revisit

Direction: Option 1. DEFINE pending user confirmation.
