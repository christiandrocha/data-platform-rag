# BUILD REPORT: Corpus acquisition and chunk measurement

## Metadata

| Field | Value |
|-------|-------|
| Feature | corpus-indexing (slice 1 of 2) |
| DEFINE | [DEFINE.md](DEFINE.md) |
| DESIGN | [DESIGN.md](DESIGN.md) |
| Start date | 2026-09-17 |
| End date | 2026-09-17 — **paused**, see Known gaps |
| PR | not raised |

## What was built

**New**

- `data_platform_rag/indexer/corpus.py` — the single owner of the in-corpus file
  set (`IN_CORPUS`), snapshot resolution, and manifest reading.
- `data_platform_rag/indexer/tokenizer.py` — real token counting, or a loud
  failure. Never a word-count proxy.
- `scripts/fetch_corpus.py` — clone, extract, hash, manifest, delete the clone.
- `contracts.py`: `CorpusFile`, `CorpusProject`, `CorpusManifest`, `Chunk`.
- `docs/adr/ADR-012-corpus-snapshot-lifecycle.md` (committed earlier, `1b18ab6`).

**Changed**

- `indexer/chunker.py` — ADR-007 implemented: per-type strategy, the rule-3 split
  hierarchy, ADR preambles, and the rule-4 loud failure.
- `indexer/loader.py` — `load_corpus` implemented against the snapshot.
- `scripts/index_corpus.py` — `--dry-run` with the inventory staleness check.
- `scripts/verify_adversarials.py`, `scripts/audit_questions.py` — both now import
  the shared corpus module; `IN_CORPUS_SUBPATHS` and the duplicated
  `resolve_corpus_dir` are gone.
- `Makefile` — `fetch-corpus`, `index-corpus-dry`, a complete `.PHONY`, and
  `PYTHONPATH`.
- `pyproject.toml` — `pythonpath = ["."]` for pytest.

**Tests**: 36 added (49 → 85). `tests/unit/test_corpus.py` (18),
`tests/unit/test_chunker.py` (17 with parametrisation),
`tests/integration/test_fetch_corpus.py` (6, against local git fixtures — no
network).

**Measured against the real corpus** at `sdd-kafka-databricks@f1295df9` and
`sdd-kafka-snowflake-2@82a2e269`: 47 files extracted (31 + 16), 307 chunks.

## What deviated from design

1. **`Chunk` became a pydantic model, in this slice.** DESIGN listed dev-log #1 as
   a non-goal until the writer exists. Implementing the real chunker forced its
   return type, and returning the drifted dataclass would have entrenched the
   divergence. Dev-log #1 is resolved: flat `str` fields replaced by nested
   `ChunkMetadata`, matching `RetrievedChunk`.

2. **`in_corpus_files()` was split in two.** DESIGN specified
   `-> list[Path]`; the manifest needs each file's `source_type`, and classifying
   twice would be a second place to get it wrong. `classified_files()` returns
   `(Path, SourceType)` pairs; `in_corpus_files()` is the thin path-only wrapper
   the gate uses.

3. **`repo_url` is `AnyUrl`, not `HttpUrl`.** Acquisition could otherwise only be
   tested with network access. A `file://` URL is a valid clone source, and the
   integration tests clone local fixture repos.

4. **The body budget is computed, not the 480 constant.** ADR-007 assumes
   `512 - 480 = 32` tokens is always enough for the preamble. It is not:
   `007_pipeline_unification.md` assembled to **514** tokens with a 480-token
   body. The budget is now `min(480, 512 - preamble - 2)`. ADR-007 says the
   assertion rather than the estimate is the guarantee, so this honours it —
   but the ADR's stated numbers are now known to be approximate, and that is worth
   an amendment.

5. **Type-specific splitters run before the paragraph split.** ADR-007 names
   top-level YAML keys and SQL statements explicitly. Splitting on blank lines
   first reached the same verdict but reported it against `<document root>`
   instead of naming the `schema` key that overflowed.

6. **README lead-block handling is unspecified by ADR-007.** The `# Title` line
   becomes the preamble of every section, so a section retrieved alone says which
   project it came from — the two READMEs share section names ("Stack",
   "Architecture", "The Problem"). Any substantive remainder becomes its own
   chunk rather than being dropped.

7. **`chunk_index` for `contract` and `macro` may be non-zero.** ADR-007's
   metadata table says `0`; its own oversize note authorises splitting those types
   at YAML keys or statements, and a split file needs ordinals. The table and the
   note disagree; the note governs the case that actually occurs.

8. **Two environment fixes not in DESIGN**: `pythonpath = ["."]` in pyproject and
   `export PYTHONPATH := .` in the Makefile. `make test` had never run in a bare
   checkout (`ModuleNotFoundError: data_platform_rag`), and scripts importing the
   package hit the same wall. Neither is a design change; both were blocking.

## RAGAS delta

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Faithfulness | — | — | n/a |
| Context Precision | — | — | n/a |
| Answer Relevance | — | — | n/a |
| Context Recall | — | — | n/a |
| Fallback rate | — | — | n/a |

**Not measured, and not measurable.** No retrieval and no generation exist, and
the golden set holds 5 of 50 questions, so there is no baseline a delta could be
taken against. DEFINE deferred the WORKFLOW_CONTRACTS exit criterion "make eval
shows no regression on golden set" with this cause; it returns at slice 2.

No number is entered above, per the AGENTS.md boundary against invented RAGAS
scores.

## Known gaps at merge time

**Blocking — the feature pauses here by design.** `make index-corpus-dry` fires
ADR-007 rule 4 on two documents. Both need a human decision (reformat the source,
or record an explicit exception in ADR-007); neither is a coding task:

- `sdd-kafka-databricks/contracts/payments.yml` — the `schema` key is **551
  tokens**. ADR-007's own fallback boundary for contracts is top-level YAML keys,
  and one key still exceeds the budget. Splitting further means splitting the
  column list, which contradicts the ADR's rationale that "a data contract read in
  halves is not a data contract".
- `sdd-kafka-snowflake-2/README.md` — the `## Stack` section is a **690-token**
  markdown table, atomic by ADR-007 rule 4.

One chunk sits between the budget and the hard limit, which is expected and fine:
`008_delete_handling.md [Context]` at 483 tokens.

**Non-blocking**

- **`bandit` is not installed locally**, so `make lint` cannot be run to
  completion here. `ruff check` passes on all three trees and `yamllint` is clean.
  The bandit step is unverified, not failing.
- **`pytest-asyncio` is not installed**, so pytest warns `Unknown config option:
  asyncio_mode` on every run. Pre-existing; no async test exists yet.
- **`adr_id` is not canonicalised across the corpus's three spellings** — DEFINE
  listed it as a COULD and nothing in this slice reads it. Currently normalised to
  `ADR-<digits as written>`, unqualified by project.
- **`topic` and `keywords` are `NULL`**, as DEFINE specified.
- **The manifest is not stored in Postgres.** Slice 2 needs it there for the
  *indexed corpus == verified corpus* assertion; `schema_version` exists so the
  format can migrate.
- **`fetch-corpus` reads clone URLs through `Settings`**, falling back to the
  declared field defaults when a full `Settings` cannot be built — cloning two
  public repos should not require an Anthropic key. The fallback works but the
  coupling is inelegant.

## Verification

- [x] `ruff check data_platform_rag tests scripts` — All checks passed
- [ ] `make lint` — **incomplete**: ruff and yamllint clean, `bandit` not installed
- [x] `make test` — **85 passed** (49 before this feature)
- [x] `make fetch-corpus` — 2 projects, 47 files, manifest written, no `.git`
      surviving, full clone deleted
- [x] `make verify-adversarials` with **no `CORPUS_DIR=` override** — reaches its
      probes and passes. This is the ADR-012 acceptance test: the blocking gate now
      has a canonical input
- [x] `grep -c IN_CORPUS_SUBPATHS scripts/verify_adversarials.py` — **0**
- [x] Inventory staleness check — "inventory matches the snapshot", 21/21 ADRs
- [ ] `make index-corpus-dry` — **exits 1** on the two rule-4 documents above.
      Correct behaviour, and the reason this feature is paused rather than done
- [ ] `make eval` — not applicable, no retrieval exists
- [ ] `make verify-indexes` — not applicable, nothing was written to Postgres
