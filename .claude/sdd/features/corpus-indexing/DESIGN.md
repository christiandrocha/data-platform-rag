# DESIGN: Corpus acquisition and chunk measurement

> Implements [DEFINE.md](DEFINE.md), slice 1 of `corpus-indexing`.
> Decision of record: [ADR-012](../../../../docs/adr/ADR-012-corpus-snapshot-lifecycle.md).

## Metadata

| Field | Value |
|-------|-------|
| Feature | corpus-indexing (slice 1 of 2) |
| Depends on | [DEFINE.md](DEFINE.md), Clarity Score 14/15 |
| Status | Draft |
| ADR needed | Yes — [ADR-012](../../../../docs/adr/ADR-012-corpus-snapshot-lifecycle.md), corpus snapshot lifecycle |

## Architecture overview

Acquisition is split from indexing. Today one stub script is meant to do both;
after this slice, one target produces a snapshot and a second reads it.

```
make fetch-corpus                       make index-corpus --dry-run
      │                                            │
      ├─ shallow clone → scratch                   ├─ read MANIFEST.json
      ├─ extract in-corpus files ──┐               ├─ chunk per ADR-007
      ├─ sha256 each file          │               └─ report token distribution
      ├─ write MANIFEST.json       │                  (writes nothing)
      └─ rm -rf full clone         │
                                   ▼
                    /tmp/dpr-corpus-{ts}/
                      ├─ MANIFEST.json
                      ├─ sdd-kafka-snowflake-2/
                      └─ sdd-kafka-databricks/
                                   │
                ┌──────────────────┼──────────────────┐
                ▼                  ▼                  ▼
      verify_adversarials   audit_questions   inventory staleness check
        (ADR-011 Layer 1)     (ADR-011 L2)      (ADR-011 Consequences)
```

**New**

- `data_platform_rag/indexer/corpus.py` — the single owner of the in-corpus file
  set and of snapshot resolution. Every consumer imports from here.
- `scripts/fetch_corpus.py` — clone, extract, manifest, delete.

**Changed**

- `scripts/index_corpus.py` — the stub is replaced, but only with the `--dry-run`
  path. Embedding and writing stay unimplemented and say so.
- `scripts/verify_adversarials.py` — `IN_CORPUS_SUBPATHS` deleted;
  `in_corpus_files()` and `resolve_corpus_dir()` move to `corpus.py`.
- `scripts/audit_questions.py` — same resolution, imported not duplicated.
- `data_platform_rag/indexer/chunker.py` — implemented per ADR-007 far enough to
  emit units and token counts. It is the real chunker, not a measurement stub;
  slice 2 adds no chunking logic.
- `Makefile` — `fetch-corpus` added, `index-corpus` gains `--dry-run`.
- `AGENTS.md` — both contradicting passages, same commit as ADR-012.
- `docs/adr/index.md` — the ADR-012 row.

**Unchanged**: `sql/`, `contracts.py::ChunkMetadata`, everything under
`retrieval/`, `generation/`, `observability/`. No database is touched in this
slice.

## Data contracts

Three pydantic models in `contracts.py`, per ADR-010. `MANIFEST.json` is the
serialized `CorpusManifest`.

```python
class CorpusFile(BaseModel):
    path: str          # relative to the project directory
    sha256: str        # 64 lowercase hex
    source_type: SourceType

class CorpusProject(BaseModel):
    project: SourceProject
    repo_url: HttpUrl
    commit_sha: str    # exactly 40 hex chars, validated
    files: list[CorpusFile]

class CorpusManifest(BaseModel):
    schema_version: int          # 1
    created_at: datetime         # UTC
    projects: list[CorpusProject]
```

`schema_version` is present from the start because slice 2 must store these SHAs
beside the indexed rows, and a format that cannot be versioned cannot be migrated.

`source_type` is assigned at extraction, not at chunking, so exactly one place
decides what a file is. The mapping is the table in ADR-012 Decision 4.

## Interfaces

**New CLI**

```
scripts/fetch_corpus.py [--out-dir DIR] [--keep-old]
scripts/index_corpus.py --dry-run [--corpus-dir DIR] [--tokenizer NAME]
```

**New make targets**

```
make fetch-corpus                 # create the snapshot
make index-corpus-dry             # measure it, write nothing
```

`make index-corpus` keeps its name and still refuses to run: slice 2 owns it.

**`corpus.py` public surface**

```python
IN_CORPUS: dict[SourceProject, tuple[CorpusRule, ...]]
def resolve_snapshot(explicit: Path | None = None) -> Path
def read_manifest(snapshot: Path) -> CorpusManifest
def in_corpus_files(project_root: Path, project: SourceProject) -> list[Path]
```

`resolve_snapshot` carries the dev-log #16 invariant: a missing, empty, or
manifest-less snapshot raises rather than returning a path that covers nothing.

**Config**: no new env var. `CORPUS_REPO_SNOWFLAKE` and `CORPUS_REPO_DATABRICKS`
already exist in `.env.example`. The tokenizer defaults to
`settings.embedding_model`.

## Retrieval and RAG-specific concerns

- [x] **Does this affect chunking?** Yes — it implements ADR-007 for all four
  source types with a v1 producer (`adr`, `readme`, `macro`, `contract`).
  `schema` has no producer; ADR-012 Decision 5 records why. Nothing is persisted,
  so the chunking is measured before it is trusted.
- [x] **Does this touch the HNSW index?** No. No vector is computed, no row is
  written, no index is built or rebuilt.
- [x] **Does this change the query pattern?** No. `sql/99_verify.sql` stands.
- [x] **Does this change RAGAS metrics?** No metric exists to change. The
  WORKFLOW_CONTRACTS build exit criterion "make eval shows no regression" is
  deferred with cause in DEFINE, and returns at slice 2.

**The real RAG risk in this slice is a measurement that trips ADR-007.** Ten of
21 ADRs exceed 480 whitespace-separated words, and databricks 007 is 4,131. If an
atomic block exceeds the budget on its own, ADR-007 rule 4 requires a human
decision — reformat the source, or record an exception — and this feature pauses.
The dry run exists so that decision arrives before an embedder and a writer are
built on top of it.

## Alternatives considered

The corpus-lifecycle alternatives — clone-index-delete, pin-and-reclone,
submodules, vendoring — are argued and rejected in ADR-012. Two design-level
alternatives are local to this slice:

**Measure with a word count instead of a tokenizer.** Cheaper, no model download,
and the BRAINSTORM's word counts already suggest the answer. Rejected: ADR-007's
assertion is denominated in tokens against a 512 window, and words are not
tokens. A word-count proxy would produce a number that looks like a measurement
and is not one.

**Put extraction inside `index_corpus.py` and skip `fetch-corpus`.** One fewer
target. Rejected: it rebuilds the coupling this slice exists to break — the gate
would again depend on the indexer having run, and the gate is a precondition of
eval, not a consumer of it.

## Test plan

**Unit** (`tests/unit/`)

- `test_corpus_rules.py` — the in-corpus rule set: the six excluded files are
  excluded; a `.py` under `contracts/` is excluded while a `.yml` beside it is
  included; `docs/adr/README.md` is excluded but `docs/adr/0018_*.md` is not.
- `test_manifest.py` — `CorpusManifest` round-trips; a 39-character SHA fails
  validation; a non-hex sha256 fails.
- `test_resolve_snapshot.py` — missing, empty, and manifest-less directories each
  raise, with a message naming the cause.
- `test_chunker.py` — ADR-007 per source type against small hand-written
  fixtures, not corpus files: an ADR under budget yields one chunk; one over
  budget splits by `##` with the title preserved as preamble; an assembled chunk
  over 512 raises.

**Integration** (`tests/integration/`)

- `test_fetch_corpus.py` — against a local fixture repo created by the test, not
  the network: extraction, manifest, no surviving `.git`, and a second run
  producing an identical sha256 set.
- `test_gate_uses_corpus_module.py` — `verify_adversarials` resolves and greps a
  fixture snapshot with no `CORPUS_DIR=`, and `IN_CORPUS_SUBPATHS` is gone.
- `test_inventory_staleness.py` — an ADR in the manifest but not the inventory
  fails by name; the reverse also fails.

**Manual verification**

- `make fetch-corpus` against the real remotes, then `find` for `.git` and for
  files absent from the manifest.
- `make index-corpus-dry` and read the distribution: every unit over 480 named,
  every assembled chunk over 512 named.
- `make verify-adversarials` with no override, reaching its probes.
- Confirm whether the ADR-004 candidate models share a tokenizer. If they do, the
  token counts are final rather than provisional, and the report says so.

## Rollout plan

No schema change, no user-visible behaviour, no feature flag. The product is not
deployed, so there is nothing to roll out to.

**Order**: `corpus.py` and the contracts first; `fetch_corpus.py` second; the
consumer edits third, so the gate is never without a definition; chunker and the
dry run last; ADR-012 and the AGENTS.md edits in the commit that lands the
behaviour they describe.

**Rollback**: `git revert`. The only external state is `/tmp/dpr-corpus-*`,
removable with `rm -rf`. Reverting restores the stub and the `CORPUS_DIR=`
override that curation uses today, so nothing that works now stops working.

## Open questions

Resolved from DEFINE:

- [x] **ADR number** — ADR-012, reasoning in its Consequences. The `rerank_top_k`
  candidate takes the next number if it is ever written.
- [x] **The six disputed files** — all excluded from index and gate. ADR-012
  Decision 4.
- [x] **`schema` has no producer** — confirmed: no `.avsc` or subject file exists
  in either corpus; the subjects live in a running Schema Registry that
  `scripts/sync_metadata.py` reads over the network. Scoped out of v1, AGENTS.md
  corrected, `SourceType` untouched.
- [x] **Retention** — `fetch-corpus` deletes older snapshots; `--keep-old` opts out.
- [x] **Tokenizer** — `settings.embedding_model`, with the shared-tokenizer check
  in manual verification deciding whether the numbers are final or provisional.

Deferred to slice 2, deliberately:

- [ ] **Does the manifest belong in Postgres?** It must, for the
  *indexed == verified* assertion. `schema_version` exists so the format can move.
  The column and its migration are slice 2's.

Still open:

- [ ] **What happens if the dry run trips ADR-007 rule 4?** The process is
  decided — pause, human decision, no code. What is not decided is whether the
  answer for an oversize atomic block is reformatting a corpus repo, which edits a
  source project to suit its consumer, or recording an exception, which leaves a
  chunk that silently truncates. The choice cannot be made before the measurement
  names the block.
