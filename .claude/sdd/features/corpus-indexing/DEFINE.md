# DEFINE: Corpus acquisition and chunk measurement

> Slice 1 of `corpus-indexing`: create the canonical corpus snapshot the blocking
> eval gate already assumes exists, record what commit it came from, and measure
> the corpus against ADR-007's token rules — without writing a single row.

## Metadata

| Field | Value |
|-------|-------|
| Feature | corpus-indexing (slice 1 of 2) |
| Date | 2026-09-17 |
| Author | christiandrocha |
| Status | Ready for Design |
| Clarity Score | 14/15 |

## Problem statement

`scripts/index_corpus.py` is a 25-line stub, so the canonical corpus directory
that `verify_adversarials.py` and `audit_questions.py` resolve to — the newest
`/tmp/dpr-corpus-*` — has never existed. ADR-011 makes the first of those a
**blocking precondition of every eval** at `error` severity. The blocking gate
has no defined input, and the only way it runs today is a local `CORPUS_DIR=`
override pointed at working copies in `~/Documents` that CI does not have.

Two further holes travel with it, both found while reading the corpora at
`sdd-kafka-snowflake-2@82a2e26` and `sdd-kafka-databricks@f1295df`:

**Nothing records which corpus commit anything was measured against.**
`corpus_inventory.yml` carries `verified_against_clone: 2026-09-14` — a date, not
a SHA. The corpora are live repos. An eval can index commit X while the gate
greps commit Y, and no check compares the two. ADR-011 Commitment 2 closed this
hole for the golden set by recording the YAML's git SHA per run; the corpus is
the other half of every score and has no equivalent.

**The in-corpus file set is defined three times and the definitions disagree.**
`verify_adversarials.py` walks `rglob("*")` under `docs/adr` and `contracts`;
`corpus_inventory.yml` enumerates paths by hand; the loader will imply a third.
A gate whose scope is *wider* than the index over-blocks: a probe matching Python
code the system can never retrieve rejects a valid adversarial. This is the
failure shape of dev-log #8 and #13 — a definition that covers the wrong set does
not raise, and the gate reports green.

## Users

| User | Role | Pain point |
|------|------|-----------|
| Christian (curator) | Writes the 28 human golden-set questions | Cannot run `make verify-adversarials` or `make audit-adversarials` without an override; the corpus he reads and the corpus the gate greps are the same files only by luck |
| Christian (operator) | Runs the eval and reads its numbers | Has no way to state what corpus a score was measured against, so no score is reproducible |
| CI (`ragas.yml`) | Runs the blocking gate on every push | A runner has no `~/Documents`. With no canonical path, the gate either cannot run or runs against nothing — and a probe over nothing passes vacuously (dev-log #16) |
| ADR-004 (the embedding benchmark) | Consumes a chunked corpus | Blocked on a pipeline that does not exist. The dry run is the earliest point its input becomes measurable |

## Goals (prioritized)

| Priority | Goal |
|----------|------|
| MUST | `make fetch-corpus` clones both repos, copies **only** in-corpus files into `/tmp/dpr-corpus-{ts}/{project}/`, and deletes the full clone before exiting |
| MUST | A `MANIFEST` per snapshot: repo URL, commit SHA, and relative path + sha256 for every extracted file, as a pydantic model in `contracts.py` (ADR-010) |
| MUST | **One** definition of the in-corpus file set, owned by the extractor. `verify_adversarials.py` consumes it instead of declaring `IN_CORPUS_SUBPATHS` |
| MUST | An ADR for the lifecycle change, plus both contradicting AGENTS.md passages edited in the same pass so they cannot disagree again |
| MUST | Inventory staleness check: a set difference between the manifest and `corpus_inventory.yml`, failing loudly on either direction of drift (ADR-011 Consequences assigns this here) |
| MUST | `--dry-run` chunking that applies ADR-007 per source type and reports a token-count distribution, counted with a real tokenizer, writing nothing |
| SHOULD | A snapshot retention rule, so `/tmp` does not accumulate and "newest wins" stays meaningful (dev-log #14) |
| SHOULD | A per-file decision for the six files the gate covers and the inventory excludes (see Open questions) |
| COULD | A canonical `adr_id` form, decided and recorded, though nothing in this slice reads it |

## Success criteria (measurable)

- [ ] `make fetch-corpus` exits 0 and produces exactly **2** project directories under one `/tmp/dpr-corpus-{ts}/`
- [ ] The full clone is gone: **0** files remain under the snapshot that are not in the manifest, and **0** `.git` directories survive
- [ ] The manifest records a **40-character commit SHA** per project and a **sha256** per file, with **0** entries missing either
- [ ] The manifest covers all **21** inventory ADRs (12 snowflake + 9 databricks), all **21** databricks YAML contracts, and all **3** dbt macros
- [ ] Re-running `make fetch-corpus` against unchanged remotes produces a manifest whose per-file sha256 set is **identical** — the snapshot is reproducible
- [ ] `grep -c IN_CORPUS_SUBPATHS scripts/verify_adversarials.py` returns **0**; the gate and the extractor agree by construction, not by review
- [ ] The inventory check reports the set difference in **both** directions and exits non-zero if it is non-empty in either
- [ ] `make index-corpus --dry-run` reports, for every extracted file: unit count, and assembled token count per unit against the **512** hard limit and the **480** body budget
- [ ] The dry run **names every unit over budget** rather than summarising — the ADR-007 rule-4 decision needs the specific unit, and 10 of 21 ADRs already exceed 480 whitespace-separated words (databricks 007 is 4,131)

## Acceptance tests

- [ ] Given a clean `/tmp`, `make fetch-corpus` creates one snapshot, and `find` shows no `.git` and no file absent from the manifest
- [ ] Given a snapshot, `make verify-adversarials` runs with **no** `CORPUS_DIR=` override and reaches its probes
- [ ] Given a manifest and an inventory that agree, the staleness check exits 0; given an ADR added to one and not the other, it exits non-zero and names the file
- [ ] Given an empty or missing snapshot directory, every consumer raises rather than proceeding (the dev-log #16 invariant, extended to the extractor)
- [ ] Given the dry run, a reader can name every unit that exceeds 480 tokens and every assembled chunk that would exceed 512
- [ ] Given two consecutive dry runs on the same snapshot, the reported unit count and token counts are identical
- [ ] Given a corpus repo that gained an ADR since `verified_against_clone`, the staleness check fails before any chunking is reported

## Non-goals

Explicitly out of scope for this slice:

- **Embedding and writing to Postgres.** Slice 2. No `chunks` rows, no DDL, no
  `sentence-transformers` load. The dry run exists precisely so the token
  question is answered before the writer is built.
- **Choosing the embedding model (ADR-004).** The dry run needs *a* tokenizer to
  count with; it does not need the final one. Which tokenizer it uses, and
  whether that choice affects the counts materially, is a DESIGN question.
- **Resolving ADR-007 if the dry run trips its fail-loud rule.** If an atomic
  block exceeds the budget on its own, this feature **pauses** and the next step
  is a human decision under ADR-007 rule 4 — reformat the source, or record an
  exception. Not code.
- **`make reindex` semantics** (rebuild, truncate-in-a-transaction). Nothing is
  written in this slice, so there is nothing to rebuild.
- **`Chunk` vs `ChunkMetadata`** (dev-log #1). The lean is to delete `Chunk`, but
  it is only forced when the writer exists.
- **`topic` and `keywords` population.** Both stay `NULL`; the schema already
  defines `keywords IS NULL` as "extraction did not run".
- **The `schema` source type.** See Open questions — it may be scoped out of v1
  entirely, which is a correction to AGENTS.md, not an implementation task.

## Open questions

- [ ] **Which ADR number does the lifecycle decision take?** `ADR-012` is
  informally held by the `rerank_top_k` candidate (dev-log #9), which
  deliberately has no file and may never earn one. Either reassign 012 here and
  record it, or take 013 and leave the gap. The number must be decided before the
  ADR is written, because the index is chronological.
- [ ] **The six disputed files.** The gate covers, and the inventory excludes:
  `sdd-kafka-snowflake-2/docs/adr/README.md` (an ADR index, 579 words) and five
  Python files under `sdd-kafka-databricks/contracts/` (`__init__.py`,
  `dlt_adapter.py`, `loader.py`, `pydantic_models.py`, `spark_schema.py`). Each
  needs one decision: index it under which `source_type`, or exclude it from the
  gate too. Indexing Python source would also sit close to the
  "no source code" exclusion in PRE_BUILD_VALIDATION Section 2.
- [ ] **`schema` has no producer.** At `82a2e26` no `.avsc` or registry subject
  files exist; only ADR-0030 discusses the Schema Registry. `SourceType` carries
  a value nothing emits, ADR-007 has a strategy row for it, and AGENTS.md claims
  "Schema Registry contracts" as corpus. Find where the subjects live, or scope
  `schema` out of v1 and correct the claim.
- [ ] **Which tokenizer does the dry run count with,** given ADR-004 is unmade?
  `bge-small-en-v1.5` is the config default and the likely winner, but counting
  with it and reporting the number as final would pre-empt the benchmark.
- [ ] **Retention.** Does `fetch-corpus` delete older snapshots, or do consumers
  select by the SHA the manifest records rather than by mtime? "Newest wins" plus
  no cleanup is the dev-log #14 shape.
- [ ] **Does the manifest belong in Postgres too?** The eval needs to assert
  *indexed corpus == verified corpus*, which implies the SHA is stored beside the
  rows. That is a schema change, and it belongs to slice 2 — but deciding it late
  risks a manifest format that cannot express what slice 2 needs.

## Deferred exit criterion

`WORKFLOW_CONTRACTS.yaml` requires, for BUILD, that "make eval shows no
regression on golden set". **Explicitly deferred for this slice**, with cause: no
retrieval and no generation exist, and the golden set stands at 5 of 50, so there
is no baseline a regression could be measured against. The structural acceptance
tests above stand in its place — reproducible snapshot, deterministic unit and
token counts, manifest–inventory agreement, and loud failure on an absent corpus.

The criterion returns, unmodified, at slice 2.

## Clarity Score self-check

Rate each 1-5. Total must be >= 12/15 to proceed to Design.

| Dimension | Score | Notes |
|-----------|-------|-------|
| Problem is specific and testable | 5 | Three named holes, each with a mechanical test. The scope boundary was resolved before writing: the AGENTS.md rule limits what is indexed, not what touches disk, so only in-corpus files survive the run |
| Users are named and their pain is real | 4 | The curator's pain is present-tense and blocking. Not a 5 for the same reason as golden-set-curation: two of four rows are consumers, not people, and the dimension is stretched to cover them |
| Success criteria include numbers | 5 | Every criterion is numeric or a set comparison, and all are checkable without a database. The token criteria deliberately measure and name rather than assert a pass — whether the corpus fits ADR-007 is unknown, and a criterion that presumed the answer would be a fabricated number |
| **Total** | **14/15** | Above the 12/15 gate |
